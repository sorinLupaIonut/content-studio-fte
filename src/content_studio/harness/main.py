"""FastAPI entry point for the Content Studio control plane."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager
from uuid import UUID

from fastapi import Depends, FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from content_studio.config import (
    HARNESS_HOST,
    HARNESS_PORT,
    UI_DEV_ORIGINS,
    UI_STATIC_DIR,
)
from content_studio.debug import attach_if_requested
from content_studio.harness.auth import Identity, IdentityError, IdentityResolver
from content_studio.harness.chat import ChatRunAccepted, ChatRunRequest
from content_studio.harness.generation import (
    GenerationStartRequest,
    VariantSelectionRequest,
    encode_sse,
)
from content_studio.harness.models import (
    DecisionsRequest,
    HealthResponse,
    MeResponse,
    PendingResponse,
    ProfileSectionsResponse,
    ProfileUpdateRequest,
    RunRequest,
    RunResponse,
    TrustedDecisionsRequest,
)
from content_studio.harness.posts import PostUpdateRequest, SavePostsRequest
from content_studio.harness.service import HarnessError, HarnessService
from content_studio.harness.static_ui import mount_ui


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

    app = FastAPI(title="Content Studio Harness", version="0.1.0", lifespan=lifespan)
    if resolver.settings.mode == "development":
        app.add_middleware(
            CORSMiddleware,
            allow_origins=list(UI_DEV_ORIGINS),
            allow_credentials=False,
            allow_methods=["GET", "POST", "PUT", "OPTIONS"],
            allow_headers=["Content-Type", "Idempotency-Key"],
        )

    def authenticated(request: Request) -> Identity:
        return request.app.state.identity.resolve(request.headers)

    identity_dependency = Depends(authenticated)

    @app.exception_handler(HarnessError)
    async def harness_error(_request: Request, exc: HarnessError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.exception_handler(IdentityError)
    async def identity_error(_request: Request, exc: IdentityError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        return await request.app.state.harness.health()

    @app.post("/runs", response_model=RunResponse)
    async def create_run(
        body: RunRequest,
        request: Request,
        response: Response,
        _identity: Identity = identity_dependency,
    ) -> RunResponse:
        result = await request.app.state.harness.run(body.message, body.session_id)
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
            run_id, body.session_id, body.decisions, identity.principal_id
        )
        if result.status == "pending":
            response.status_code = 202
        return result

    @app.get("/api/me", response_model=MeResponse)
    async def me(
        identity: Identity = identity_dependency,
    ) -> MeResponse:
        return MeResponse(
            principal_id=identity.principal_id,
            email=identity.email,
            provider=identity.provider,
            is_development=identity.is_development,
        )

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
        _body: VariantSelectionRequest,
        request: Request,
        identity: Identity = identity_dependency,
    ) -> dict:
        return await request.app.state.harness.select_generation_variant(
            identity.principal_id, variant_id
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
