"""FastAPI entry point for the Content Studio control plane."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from content_studio.config import (
    AUTH_SELF_PROVISION_PROVIDERS,
    CLIENT_OWNER_EMAIL,
    CLIENT_SLUG,
    HARNESS_HOST,
    HARNESS_PORT,
    UI_DEV_ORIGINS,
    UI_STATIC_DIR,
    models_for,
)
from content_studio.debug import attach_if_requested
from content_studio.harness.accounts import BudgetExhausted
from content_studio.harness.auth import Identity, IdentityError, IdentityResolver
from content_studio.harness.chat import ChatRunAccepted, ChatRunRequest
from content_studio.harness.errors import CodedError
from content_studio.harness.generation import (
    GenerationStartRequest,
    VariantSelectionRequest,
    encode_sse,
)
from content_studio.harness.limits import RateLimiter, is_limited, key_for
from content_studio.harness.models import (
    DecisionsRequest,
    HealthResponse,
    MeResponse,
    PendingResponse,
    ProfileSectionsResponse,
    ProfileUpdateRequest,
    RunRequest,
    RunResponse,
    SetBudgetRequest,
    SetDisabledRequest,
    TrustedDecisionsRequest,
)
from content_studio.harness.posts import PostUpdateRequest, SavePostsRequest
from content_studio.harness.service import HarnessError, HarnessService
from content_studio.harness.static_ui import mount_ui
from content_studio.language import normalise
from content_studio.observability import configure as configure_observability
from content_studio.observability import shutdown_phoenix


def create_app(
    service_factory: Callable[[], HarnessService] = HarnessService,
    identity_resolver: IdentityResolver | None = None,
) -> FastAPI:
    service = service_factory()
    resolver = identity_resolver or IdentityResolver()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        resolver.validate_startup()
        app.state.harness = service
        app.state.identity = resolver
        await service.start()
        try:
            yield
        finally:
            await service.close()
            # Configured here, so shut down here. The batch processor holds
            # spans for a few seconds; without this the last run of a revision
            # is the one that never reaches Phoenix.
            shutdown_phoenix()

    app = FastAPI(title="Content Studio Harness", version="0.1.0", lifespan=lifespan)

    # Before any middleware, so the server span wraps the whole request rather
    # than the part of it that survived the rate limiter.
    app.state.observability = configure_observability(app)

    limiter = RateLimiter()

    @app.middleware("http")
    async def rate_limit(request: Request, call_next):
        if is_limited(request.url.path):
            peer = request.client.host if request.client else None
            wait = limiter.retry_after(key_for(request.headers, peer))
            if wait is not None:
                # A code, not a sentence: the interface is bilingual and owns
                # the wording. `Retry-After` is what a well-behaved client obeys
                # without anyone reading anything.
                return JSONResponse(
                    status_code=429,
                    content={"detail": "rate limited", "code": "rate_limited"},
                    headers={"Retry-After": str(wait)},
                )
        return await call_next(request)

    if resolver.settings.mode == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(UI_DEV_ORIGINS),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    async def authenticated(request: Request) -> Identity:
        identity = request.app.state.identity.resolve(request.headers)
        # One place, every route: the client this request may touch is pinned to
        # the request's context here and read again inside `_data_mcp`. Cached
        # for a minute, so this is a round trip once per principal per minute,
        # not once per request.
        slug = await request.app.state.harness.accounts.bind(identity.principal_id)

        # A principal from a self-allowlisting provider gets a studio written on
        # its first request. Handled before the owner fall-through below and
        # returning early, because none of that reasoning applies here: such a
        # principal has no business ever being scoped to `CLIENT_SLUG`, not even
        # for the moment the data plane is unreachable. Where the fall-through
        # asks "is this the owner?", this asks "does this person have their own
        # studio yet?" and makes one if not.
        if identity.may_self_provision:
            accounts = request.app.state.harness.accounts
            try:
                account = await accounts.account_for(identity.principal_id)
            except Exception as exc:  # noqa: BLE001
                # `bind` degrades to CLIENT_SLUG when the data server is down.
                # For everyone else that is a harmless default; here it would be
                # somebody else's profile, library and allowance. Refuse instead.
                raise CodedError(
                    503, "account lookup unavailable", "account_lookup_failed"
                ) from exc
            if account is None:
                account = await accounts.provision_self(
                    identity.principal_id,
                    identity.email,
                    identity.provider,
                    identity.display_name,
                )
                if account is None:
                    # A row exists and does not resolve, which means suspended.
                    # Provisioning deliberately will not undo that.
                    raise CodedError(
                        403, "account not provisioned", "account_not_provisioned"
                    )
                # Re-bind: the first call pinned CLIENT_SLUG, because at that
                # moment this person genuinely had no client of their own.
                await accounts.bind(identity.principal_id)
            return identity

        # Falling through to `CLIENT_SLUG` is right for exactly one person: the
        # client the studio predates accounts for. For anyone else it would hand
        # a stranger her profile, her library and her allowance - the one
        # failure this whole tenancy layer exists to prevent. Being on the
        # allowlist buys entry to the studio, not entry to somebody's account.
        # Not in development: there the identity is synthetic, there is one
        # person at one laptop, and nobody's account can be reached by mistake.
        if (
            CLIENT_OWNER_EMAIL
            and resolver.settings.mode != "development"
            and slug == CLIENT_SLUG
        ):
            accounts = request.app.state.harness.accounts
            if identity.email.lower() == CLIENT_OWNER_EMAIL:
                # The owner reached her studio without an `app_users` row, which
                # is how it worked before accounts existed. Record the principal
                # against the client she already has, so that she appears on the
                # admin page under her address and can be suspended and restored
                # there like everybody else. Until this, the one account the page
                # could not act on was the actual client's.
                #
                # Errors let her through instead of stopping her, the opposite of
                # the branch above, and for the opposite reason: there the
                # fallback is somebody else's studio, here it *is* hers. A row
                # that could not be written is bookkeeping that failed, and
                # bookkeeping does not get to lock the client out of her own
                # work.
                try:
                    account = await accounts.account_for(identity.principal_id)
                    if account is None:
                        account = await accounts.provision_self(
                            identity.principal_id,
                            identity.email,
                            identity.provider,
                            identity.display_name,
                            client_slug=CLIENT_SLUG,
                        )
                        if account is None:
                            # A row exists and does not resolve: suspended, by
                            # somebody who meant it. That is the whole point of
                            # writing the row, so it is honoured here.
                            raise CodedError(
                                403,
                                "account not provisioned",
                                "account_not_provisioned",
                            )
                        await accounts.bind(identity.principal_id)
                except CodedError:
                    raise
                except Exception:  # noqa: BLE001
                    return identity
                return identity

            known = await accounts.provisioned(identity.principal_id)
            if known is False:
                raise CodedError(
                    403, "account not provisioned", "account_not_provisioned"
                )
        return identity

    identity_dependency = Depends(authenticated)

    async def administrator(request: Request) -> Identity:
        """Same as `authenticated`, plus a role check.

        A dependency rather than a line inside each handler, so that forgetting
        it on a new admin route is a visible omission at the top of the function
        instead of a silent leak of everybody's spending.
        """
        identity = await authenticated(request)
        account = await request.app.state.harness.accounts.account_for(
            identity.principal_id
        )
        if account is None or not account.is_admin:
            raise IdentityError(403, "this page is for the administrator only")
        return identity

    admin_dependency = Depends(administrator)

    @app.exception_handler(HarnessError)
    async def harness_error(_request: Request, exc: HarnessError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(IdentityError)
    async def identity_error(_request: Request, exc: IdentityError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(CodedError)
    async def coded_error(_request: Request, exc: CodedError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"detail": exc.detail, "code": exc.code},
        )

    @app.exception_handler(BudgetExhausted)
    async def budget_exhausted(_request: Request, exc: BudgetExhausted) -> JSONResponse:
        # 402 Payment Required, which is exactly what this is. The body carries a
        # code rather than a sentence: the interface is bilingual and picks the
        # wording, and the wording must not leak what anything cost.
        return JSONResponse(
            status_code=402,
            content={"detail": "budget exhausted", "code": "budget_exhausted"},
        )

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        return await request.app.state.harness.health(
            observability=request.app.state.observability
        )

    @app.post("/runs", response_model=RunResponse)
    async def create_run(
        body: RunRequest,
        request: Request,
        response: Response,
        _identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.run(
            body.message, body.session_id, body.language
        )
        if result.status == "pending":
            response.status_code = 202
        return result

    @app.get("/sessions/{session_id}/pending", response_model=PendingResponse)
    async def pending(
        session_id: str,
        request: Request,
        _identity: Identity = identity_dependency,
    ) -> PendingResponse:
        return await request.app.state.harness.pending(session_id)

    @app.post("/runs/{run_id}/decisions", response_model=RunResponse)
    async def decide(
        run_id: str,
        body: DecisionsRequest,
        request: Request,
        response: Response,
        identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.decide(
            run_id, body.session_id, body.decisions, identity.principal_id, body.language
        )
        if result.status == "pending":
            response.status_code = 202
        return result

    @app.get("/api/auth/options")
    async def auth_options() -> dict:
        """Which sign-in buttons the access screen should draw.

        Deliberately public - it is read by a browser that has not signed in yet,
        which is the whole point, and it discloses nothing that the sign-in page
        does not already show. No identity dependency here, and nothing about
        who may enter: that answer stays in `authenticated`.

        Driven by configuration so that adding the provider is a deployment of
        the allowlist kind (`-SkipBuild`) rather than a rebuild of the interface.
        Until AUTH_SELF_PROVISION_PROVIDERS names one, the button does not exist
        and cannot lead anyone to a `/.auth/login/` path Easy Auth would 404.
        """
        providers = AUTH_SELF_PROVISION_PROVIDERS
        return {"password_provider": providers[0] if providers else None}

    @app.get("/api/me", response_model=MeResponse)
    async def me(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> MeResponse:
        account = await request.app.state.harness.accounts.account_for(
            identity.principal_id
        )
        return MeResponse(
            principal_id=identity.principal_id,
            email=identity.email,
            provider=identity.provider,
            is_development=identity.is_development,
            is_admin=account.is_admin if account is not None else False,
            client_slug=account.client_slug if account is not None else None,
            client_name=account.client_name if account is not None else None,
            models=list(models_for(account.client_slug if account else None)),
        )

    @app.get("/api/me/usage")
    async def my_usage(
        request: Request,
        _identity: Identity = identity_dependency,
    ) -> dict:
        """How much of the allowance is gone, as a percentage. Nothing else.

        No cost, no token counts, no model name, no limit in dollars. Hiding the
        figure in the interface would not hide it - anyone can read a JSON
        response - so the split is here, on the server.
        """
        budget = await request.app.state.harness.accounts.budget_for()
        if budget is None:
            return {"percent_used": 0, "exhausted": False}
        return {"percent_used": budget.percent, "exhausted": budget.exhausted}

    @app.get("/api/admin/accounts")
    async def admin_accounts(
        request: Request,
        _identity: Identity = admin_dependency,
    ) -> dict:
        accounts = request.app.state.harness.accounts
        usage = {row["client_slug"]: row for row in await accounts.all_usage()}
        items = []
        for account in await accounts.all_accounts():
            row = usage.get(account["client_slug"], {})
            items.append({**account, **row})
        return {"items": items}

    @app.put("/api/admin/accounts/{principal_id}/disabled")
    async def admin_set_disabled(
        principal_id: str,
        body: SetDisabledRequest,
        request: Request,
        identity: Identity = admin_dependency,
    ) -> dict:
        # The one account an administrator must not be able to suspend is their
        # own: there is no second admin to undo it, and the only way back would
        # be `db/provision.py` from a terminal. Cheap rail, expensive omission.
        # Codes, not sentences. The interface is bilingual and owns the
        # wording; a Romanian sentence from the server is a Romanian sentence on
        # an English page, which is exactly what the language switch exists to
        # prevent.
        if body.disabled and principal_id == identity.principal_id:
            raise CodedError(400, "cannot suspend self", "cannot_suspend_self")
        # No administrator is suspendable from here, not only the one asking.
        # `db/provision.py` is the only thing that makes an admin, deliberately;
        # a page that can unmake one is the same page with the sign reversed.
        # Only on the way in: a restore needs no such check, and could not run
        # one anyway, because a suspended row does not resolve.
        if body.disabled:
            target = await request.app.state.harness.accounts.account_for(principal_id)
            if target is not None and target.is_admin:
                raise CodedError(400, "cannot suspend an admin", "cannot_suspend_admin")
        account = await request.app.state.harness.accounts.set_disabled(
            principal_id, body.disabled
        )
        if account is None:
            raise CodedError(404, "account not found", "account_not_found")
        return {"account": account}

    @app.put("/api/admin/accounts/{client_slug}/budget")
    async def admin_set_budget(
        client_slug: str,
        body: SetBudgetRequest,
        request: Request,
        _identity: Identity = admin_dependency,
    ) -> dict:
        value = await request.app.state.harness.accounts.set_budget(
            client_slug, body.budget_micros
        )
        return {"budget_micros": value}

    @app.get("/api/profile/sections", response_model=ProfileSectionsResponse)
    async def profile_sections(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> ProfileSectionsResponse:
        return await request.app.state.harness.profile_sections(identity.principal_id)

    @app.post(
        "/api/profile/sections/{section_key}/runs",
        response_model=RunResponse,
        status_code=202,
    )
    async def prepare_profile_update(
        section_key: str,
        body: ProfileUpdateRequest,
        request: Request,
        response: Response,
        identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.prepare_profile_update(
            identity.principal_id, section_key, body.blocks
        )
        if result.status == "completed":
            response.status_code = 200
        return result

    @app.post("/api/runs/{run_id}/decisions", response_model=RunResponse)
    async def trusted_decide(
        run_id: str,
        body: TrustedDecisionsRequest,
        request: Request,
        response: Response,
        identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.decide(
            run_id,
            body.session_id,
            body.decisions,
            identity.principal_id,
            body.language,
        )
        if result.status == "pending":
            response.status_code = 202
        return result

    @app.get("/api/library")
    async def library(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return {"items": await request.app.state.harness.library(identity.principal_id)}

    @app.get("/api/posts")
    async def saved_posts(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return {
            "items": await request.app.state.harness.saved_posts(identity.principal_id)
        }

    @app.get("/api/posts/{post_id}")
    async def saved_post(
        post_id: UUID,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return {
            "post": await request.app.state.harness.saved_post(
                identity.principal_id, post_id
            )
        }

    @app.post("/api/posts/save-runs", response_model=RunResponse, status_code=202)
    async def prepare_batch_save(
        body: SavePostsRequest,
        request: Request,
        response: Response,
        identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.prepare_batch_save(
            identity.principal_id, body
        )
        if result.status == "completed":
            response.status_code = 200
        return result

    @app.post("/api/posts/{post_id}/runs", response_model=RunResponse, status_code=202)
    async def prepare_post_update(
        post_id: UUID,
        body: PostUpdateRequest,
        request: Request,
        response: Response,
        identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.prepare_post_update(
            identity.principal_id, post_id, body
        )
        if result.status == "completed":
            response.status_code = 200
        return result

    @app.post("/api/generation-batches", status_code=202)
    async def start_generation(
        body: GenerationStartRequest,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        # The model is the one field on this request that costs different money
        # per token, and it arrives from a browser. `ModelChoice` has already
        # checked that the NAME is a model this deployment prices; this checks
        # that THIS ACCOUNT may spend at that rate. The two are separate
        # questions and only the second one knows who is asking.
        if body.model is not None:
            account = await request.app.state.harness.accounts.account_for(
                identity.principal_id
            )
            allowed = models_for(account.client_slug if account else None)
            if body.model not in allowed:
                raise CodedError(
                    403,
                    f"model {body.model!r} is not available to this account",
                    "model_not_allowed",
                )
        batch = await request.app.state.harness.start_generation(
            identity.principal_id, body
        )
        return {"batch": batch}

    @app.get("/api/generation-batches/current")
    async def current_generation(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        batch = await request.app.state.harness.current_generation(
            identity.principal_id
        )
        return {"batch": batch}

    @app.get("/api/generation-batches/{batch_id}")
    async def generation_batch(
        batch_id: UUID,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        batch = await request.app.state.harness.generation_batch(
            identity.principal_id, batch_id
        )
        return {"batch": batch}

    @app.get("/api/generation-batches/{batch_id}/events")
    async def generation_events(
        batch_id: UUID,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> StreamingResponse:
        raw_sequence = request.headers.get("last-event-id", "0")
        try:
            sequence = max(0, int(raw_sequence))
        except ValueError:
            sequence = 0
        events = await request.app.state.harness.generation_events(
            identity.principal_id, batch_id, sequence
        )

        async def stream():
            async for event in events:
                yield encode_sse(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/generation-batches/{batch_id}/ideas/{ordinal}/details",
              status_code=202)
    async def develop_generation_idea(
        batch_id: UUID,
        ordinal: int,
        request: Request,
        language: str | None = None,
        identity: Identity = identity_dependency,
    ) -> dict:
        """Write the five variants for one idea, because she opened it.

        The batch writes titles only. Details are the whole cost of a run and
        she develops one idea, so they are written on demand rather than ten at
        a time - see `GenerationCoordinator.develop`.
        """
        # A query parameter rather than a body: this POST has no body and a
        # stale cached client that sends nothing must still get a post, not a
        # 422. `normalise` is the forgiving reader for exactly that reason.
        batch = await request.app.state.harness.develop_generation_idea(
            identity.principal_id,
            batch_id,
            ordinal,
            language=normalise(language),
        )
        return {"batch": batch}

    @app.post("/api/generation-batches/{batch_id}/cancel")
    async def cancel_generation(
        batch_id: UUID,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return await request.app.state.harness.cancel_generation(
            identity.principal_id, batch_id
        )

    @app.put("/api/generation-variants/{variant_id}/selection")
    async def select_generation_variant(
        variant_id: UUID,
        body: VariantSelectionRequest,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return await request.app.state.harness.select_generation_variant(
            identity.principal_id, variant_id, body.language
        )

    @app.get("/api/conversation")
    async def conversation_transcript(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        """The active conversation, verbatim from the agent's session storage.

        Dialogue whole, tool calls collapsed, plumbing absent — the window IS
        the model's input, which is what makes copy-paste testing possible.
        """
        return await request.app.state.harness.conversation_transcript(
            identity.principal_id
        )

    @app.post("/api/conversation/new")
    async def new_conversation(
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return await request.app.state.harness.new_conversation(
            identity.principal_id
        )

    @app.post("/api/chat/runs", response_model=ChatRunAccepted, status_code=202)
    async def start_chat(
        body: ChatRunRequest,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> ChatRunAccepted:
        return await request.app.state.harness.start_chat(identity.principal_id, body)

    @app.get("/api/runs/{run_id}/events")
    async def chat_events(
        run_id: str,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> StreamingResponse:
        raw_sequence = request.headers.get("last-event-id", "0")
        try:
            sequence = max(0, int(raw_sequence))
        except ValueError:
            sequence = 0
        events = await request.app.state.harness.chat_events(
            identity.principal_id, run_id, sequence
        )

        async def stream():
            async for event in events:
                yield encode_sse(event)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache, no-transform",
                "X-Accel-Buffering": "no",
            },
        )

    @app.post("/api/runs/{run_id}/cancel")
    async def cancel_chat(
        run_id: str,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict[str, str]:
        return await request.app.state.harness.cancel_chat(identity.principal_id, run_id)

    mount_ui(app, UI_STATIC_DIR)

    return app


# No-op unless DEBUGPY_PORT is set. Module level rather than inside `run()`,
# because uvicorn is normally handed the import string `…main:app` and never calls
# the console entry point — locally from launch.json, and in the container too.
attach_if_requested("harness")

app = create_app()


def run() -> None:
    """Console entry point used locally; Azure supplies the same host and port."""
    import uvicorn

    uvicorn.run("content_studio.harness.main:app", host=HARNESS_HOST, port=HARNESS_PORT)
