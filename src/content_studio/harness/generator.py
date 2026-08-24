"""Title-first generation with durable MCP drafts and bounded E2B concurrency."""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from typing import Any
from uuid import UUID

from agents import ModelSettings, Runner
from agents.mcp import MCPServerStreamableHttp
from agents.run_config import RunConfig, SandboxRunConfig

from content_studio.audit import Audit
from content_studio.config import (
    GENERATION_CONCURRENCY,
    GENERATION_DETAIL_MODEL,
    GENERATION_TITLE_MODEL,
    MODEL,
)
from content_studio.harness.drafts import GenerationDraftClient, tool_payload
from content_studio.harness.generation import (
    GenerationBatchRequest,
    GenerationStartRequest,
    IdeaTitle,
    IdeaTitles,
    StreamEvent,
    detail_output_type,
    detail_prompt,
    public_batch,
    title_prompt,
)
from content_studio.language import DEFAULT_LANGUAGE, Language
from content_studio.observability import bind_run
from content_studio.worker import build_sandbox, build_worker, read_profile

RUN_TIMEOUT_SECONDS = 600

#: Every run in a batch - the title pass, the ten detail passes and any retry -
#: carries this workflow name and the batch id as its group. The runs already
#: shared one trace, because the trace context propagates into the tasks spawned
#: under it; what they did not share was a name, so a lot read as a dozen nested
#: spans all called "Agent workflow" and there was no way to tell a lot from the
#: run of a single idea. Note that `group_id` does NOT become Phoenix's
#: `session.id` - checked on 2026-08-23, Sessions stayed at 0 - it is a
#: correlation field, nothing more. Read by whoever is debugging, so English.
GENERATION_WORKFLOW = "Generation batch"
SOURCE_TEXT_LIMIT = 2_000


# `safe_generation_error` deliberately hands the client a short Romanian sentence
# and the exception class name — she must never read a stack trace. The operator
# still needs one, so both boundaries below log it here. Second half of D7; the
# first was the 502 handler in service.py.
logger = logging.getLogger("content_studio.harness.generator")


class ActiveBatchError(RuntimeError):
    """A principal must explicitly replace their current draft."""


class GenerationAccessError(RuntimeError):
    """A batch or variant does not belong to the authenticated principal."""


def safe_generation_error(exc: BaseException) -> str:
    """Return a useful error without account, prompt or source content."""

    name = type(exc).__name__
    message = str(exc).lower()
    if "rate limit" in message or name == "RateLimitError":
        return "Limita temporară a modelului a fost atinsă."
    if "invalid json" in message or "structured output" in message:
        return "Modelul nu a respectat formatul structurat."
    if "max turns" in message:
        return "Skill-ul nu a terminat în limita de pași."
    if isinstance(exc, asyncio.TimeoutError):
        return "Generarea a depășit timpul maxim."
    return f"Generarea a eșuat ({name})."


def retryable_generation_error(exc: BaseException) -> bool:
    message = str(exc).lower()
    return any(
        marker in message
        for marker in ("rate limit", "invalid json", "structured output", "timeout")
    ) or isinstance(exc, asyncio.TimeoutError)


def _trim_source(value: Any) -> Any:
    """Bound excerpts before they are persisted and repeated into ten prompts."""

    if isinstance(value, str):
        return value[:SOURCE_TEXT_LIMIT]
    if isinstance(value, list):
        return [_trim_source(item) for item in value[:20]]
    if isinstance(value, dict):
        return {key: _trim_source(item) for key, item in value.items()}
    return value


async def collect_source_packet(
    server: MCPServerStreamableHttp,
    drafts: GenerationDraftClient,
    request: GenerationBatchRequest,
) -> dict[str, Any]:
    """Gather each selected source exactly once before any model generation."""

    description = request.focus or (
        f"Idei pentru pilonul {request.pillar}, în format {request.format}, "
        "potrivite profilului Viorelei."
    )
    packet: dict[str, Any] = {
        "source": request.source,
        "topic": description,
        "profile": "Profilul complet este deja în instrucțiunile agentului.",
    }

    if request.source in {"Memorie", "Combinat"}:
        packet["recent_posts"] = tool_payload(
            await server.call_tool(
                "list_posts",
                {"pillar": request.pillar, "format": request.format, "limit": 12},
            ),
            # A client who has not saved anything yet is the normal first run,
            # not a failure of `content-data`.
            empty=[],
        )

    if request.source in {"Cărți", "Combinat"}:
        library = await drafts.library()
        by_id = {str(item["id"]): item for item in library}
        selected = [by_id.get(str(item_id)) for item_id in request.material_ids]
        if any(item is None for item in selected):
            raise ValueError("Cel puțin o carte selectată nu mai există în bibliotecă.")
        titles = [str(item["title"]) for item in selected if item is not None]
        passages = tool_payload(
            await server.call_tool(
                "search_books",
                {"description": description, "titles": titles or None, "limit": 8},
            ),
            empty=[],
        )
        packet["books"] = passages
        packet["book_filter"] = titles
        scores = [float(item.get("score", 0)) for item in passages]
        packet["books_relevant"] = bool(scores and max(scores) >= 0.35)

    if request.source in {"Internet", "Combinat"}:
        web = tool_payload(
            await server.call_tool(
                "search_web", {"description": description, "limit": 5}
            )
        )
        if not isinstance(web, dict) or web.get("status") != "ok":
            raise RuntimeError("Căutarea web nu a furnizat un rezultat utilizabil.")
        packet["web"] = web

    return _trim_source(packet)


def describe_batch(request: GenerationBatchRequest) -> str:
    """What was asked for, as one line, for `runs.input_message`.

    Romanian and readable, because this is the column a person reads in
    `replay.py` when they want to know what a run was even about.
    """
    parts = [f"10 idei · {request.pillar} · {request.source} · {request.format}"]
    if request.focus:
        parts.append(f"focus: {request.focus}")
    if request.material_ids:
        parts.append(f"{len(request.material_ids)} materiale")
    return " — ".join(parts)


class GenerationCoordinator:
    """Own background batch tasks while all durable state remains in MCP."""

    def __init__(
        self,
        data_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        internal_mcp_factory: Callable[[str], MCPServerStreamableHttp],
        accounts: Any | None = None,
    ) -> None:
        self._data_mcp_factory = data_mcp_factory
        self._internal_mcp_factory = internal_mcp_factory
        # Optional so a test can build a coordinator without a meter behind it.
        self._accounts = accounts
        self._tasks: dict[UUID, asyncio.Task[None]] = {}
        self._principal_tasks: dict[str, UUID] = {}

    async def close(self) -> None:
        tasks = list(self._tasks.values())
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        self._tasks.clear()
        self._principal_tasks.clear()

    async def start(
        self,
        principal_id: str,
        start_request: GenerationStartRequest,
        trail: Audit | None = None,
    ) -> dict[str, Any]:
        request = GenerationBatchRequest.model_validate(
            start_request.model_dump(exclude={"replace_current", "language"})
        )
        current = await self.current(principal_id, public=False)
        if current is not None and not start_request.replace_current:
            raise ActiveBatchError(
                "Există deja un lot curent. Confirmă înlocuirea lui ca să continui."
            )

        if start_request.replace_current:
            await self._cancel_principal_task(principal_id)

        session_id = self._session_id("generation", principal_id)
        data_mcp = self._data_mcp_factory(session_id)
        internal_mcp = self._internal_mcp_factory(session_id)
        try:
            await asyncio.gather(data_mcp.connect(), internal_mcp.connect())
            _, profile_md = await read_profile(data_mcp)
            drafts = GenerationDraftClient(internal_mcp)
            source_packet = await collect_source_packet(internal_mcp, drafts, request)
            batch = await drafts.create(principal_id, request, source_packet)
        finally:
            await asyncio.gather(
                data_mcp.cleanup(), internal_mcp.cleanup(), return_exceptions=True
            )

        batch_id = UUID(str(batch["id"]))

        # The run is opened HERE, before the task exists, for the same reason
        # `open_run` writes its row before the model is called: the id has to
        # exist for anything to hang off it. `open_run` also calls `bind_run`,
        # and `asyncio.create_task` copies the current context - so the
        # background task and every task it spawns inherit the id without a
        # single call site passing it. `_generate` binds again anyway; see there.
        #
        # Until 2026-08-23 this path opened no run at all. Costs were metered, so
        # budgets were right, but there was no `runs` row, no `public.traces`
        # (the processor drops a trace whose run is "-"), and `replay.py` could
        # not reconstruct a generation. Chat was covered; the product's main
        # feature was not.
        run_id = None
        if trail is not None:
            run_id = await trail.open_run(session_id, describe_batch(request))

        task = asyncio.create_task(
            self._generate(
                batch_id,
                principal_id,
                session_id,
                request,
                profile_md,
                source_packet,
                start_request.language,
                trail,
                run_id,
            ),
            name=f"generation-{batch_id}",
        )
        self._tasks[batch_id] = task
        self._principal_tasks[principal_id] = batch_id
        task.add_done_callback(
            lambda done, value=batch_id, owner=principal_id: self._task_done(
                value, owner, done
            )
        )
        return public_batch(batch)

    async def current(
        self, principal_id: str, *, public: bool = True
    ) -> dict[str, Any] | None:
        session_id = self._session_id("generation-read", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            value = await GenerationDraftClient(internal).current(principal_id)
        finally:
            await internal.cleanup()
        return public_batch(value) if public and value is not None else value

    async def get(self, principal_id: str, batch_id: UUID) -> dict[str, Any]:
        raw = await self._get_raw(principal_id, batch_id)
        return public_batch(raw)

    async def library(self, principal_id: str) -> list[dict[str, Any]]:
        session_id = self._session_id("library", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            return await GenerationDraftClient(internal).library()
        finally:
            await internal.cleanup()

    async def select(
        self, principal_id: str, variant_id: UUID
    ) -> dict[str, Any]:
        session_id = self._session_id("generation-select", principal_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            return await GenerationDraftClient(internal).select(
                variant_id, principal_id
            )
        finally:
            await internal.cleanup()

    async def variant_context(
        self, principal_id: str, variant_id: UUID
    ) -> dict[str, Any]:
        """Return one server-verified active variant as bounded chat context."""

        batch = await self.current(principal_id, public=False)
        if batch is None:
            raise GenerationAccessError("Nu există un lot curent pentru această țintă.")
        for idea in batch.get("ideas", []):
            for variant in idea.get("variants", []):
                if str(variant.get("id")) != str(variant_id):
                    continue
                if variant.get("status") != "ready":
                    raise GenerationAccessError("Varianta aleasă nu este încă pregătită.")
                return {
                    "kind": "generation_variant",
                    "target_id": str(variant_id),
                    "batch_id": str(batch["id"]),
                    "format": batch["format"],
                    "pillar": batch["pillar"],
                    "source_mode": batch["source"],
                    "idea": {
                        "ordinal": idea["ordinal"],
                        "title": idea["title"],
                        "angle": idea["angle"],
                    },
                    "variant": {
                        key: variant.get(key)
                        for key in (
                            "hook_type",
                            "hook",
                            "script",
                            "caption",
                            "hashtags",
                            "cta",
                            "source",
                            "format_details",
                        )
                    },
                }
        raise GenerationAccessError("Varianta nu aparține lotului curent al contului.")

    async def cancel(self, principal_id: str, batch_id: UUID) -> dict[str, Any]:
        await self._get_raw(principal_id, batch_id)
        session_id = self._session_id("generation-cancel", principal_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            result = await GenerationDraftClient(internal).cancel(
                batch_id, principal_id
            )
        finally:
            await internal.cleanup()

        task = self._tasks.get(batch_id)
        if task is not None:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task
        return result

    async def events(
        self,
        principal_id: str,
        batch_id: UUID,
        sequence: int = 0,
    ) -> AsyncIterator[StreamEvent]:
        session_id = self._session_id("generation-events", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        await internal.connect()
        drafts = GenerationDraftClient(internal)
        last_signature: str | None = None
        seen_ideas: dict[str, str] = {}
        last_heartbeat = time.monotonic()
        try:
            while True:
                raw = await drafts.get(batch_id)
                self._ensure_owner(raw, principal_id)
                public = public_batch(raw)
                signature = self._batch_signature(public)
                if signature != last_signature:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event="status",
                        batch_id=batch_id,
                        payload={"batch": public},
                    )
                    last_signature = signature

                ideas = public.get("ideas", [])
                if ideas and not seen_ideas:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event="titles.ready",
                        batch_id=batch_id,
                        payload={"batch": public},
                    )

                for idea in ideas:
                    idea_id = str(idea["id"])
                    status = str(idea["status"])
                    previous = seen_ideas.get(idea_id)
                    seen_ideas[idea_id] = status
                    if status == previous:
                        continue
                    event = {
                        "ready": "idea.ready",
                        "failed": "idea.failed",
                    }.get(status)
                    if event is not None:
                        sequence += 1
                        yield StreamEvent(
                            sequence=sequence,
                            event=event,
                            batch_id=batch_id,
                            idea_id=UUID(idea_id),
                            payload={"idea": idea},
                        )

                batch_status = str(public.get("status"))
                terminal_event = {
                    "ready": "completed",
                    "failed": "error",
                    "cancelled": "cancelled",
                    "replaced": "cancelled",
                }.get(batch_status)
                if terminal_event is not None:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event=terminal_event,
                        batch_id=batch_id,
                        payload={"batch": public},
                    )
                    return

                if time.monotonic() - last_heartbeat >= 15:
                    sequence += 1
                    yield StreamEvent(
                        sequence=sequence,
                        event="heartbeat",
                        batch_id=batch_id,
                    )
                    last_heartbeat = time.monotonic()
                await asyncio.sleep(0.8)
        finally:
            await internal.cleanup()

    async def _generate(
        self,
        batch_id: UUID,
        principal_id: str,
        session_id: str,
        request: GenerationBatchRequest,
        profile_md: str,
        source_packet: dict[str, Any],
        language: Language = DEFAULT_LANGUAGE,
        trail: Audit | None = None,
        run_id: str | None = None,
    ) -> None:
        # Redundant with the context this task inherited, and kept anyway: the
        # guarantee is then local to the task that actually runs the agent,
        # instead of resting on where `create_task` happened to be called.
        if run_id is not None:
            bind_run(run_id)

        data_mcp = self._data_mcp_factory(session_id)
        internal = self._internal_mcp_factory(session_id)
        try:
            await asyncio.gather(data_mcp.connect(), internal.connect())
            drafts = GenerationDraftClient(internal)
            # The title and detail agents are clones of this one, so the
            # language set here reaches both phases.
            base_agent = build_worker(profile_md, data_mcp, language=language)
            title_agent = base_agent.clone(
                model=GENERATION_TITLE_MODEL,
                output_type=IdeaTitles,
                model_settings=ModelSettings(
                    reasoning={"effort": "minimal"},
                    verbosity="low",
                    max_tokens=4_000,
                ),
            )
            titles = await self._run_isolated(
                title_agent,
                title_prompt(request, source_packet, language),
                IdeaTitles,
                f"{batch_id}-titles",
                str(batch_id),
            )
            await drafts.put_titles(batch_id, titles)
            await self._generate_details(
                batch_id,
                request,
                source_packet,
                titles,
                base_agent,
                drafts,
                language,
            )
            if trail is not None:
                # The titles are what the batch is judged on; the details are
                # rows of their own. One readable line, same as chat's reply.
                with suppress(Exception):
                    await trail.close_run(
                        run_id, "; ".join(idea.title for idea in titles.ideas)
                    )
        except asyncio.CancelledError:
            # A cancelled batch is not a fault, but leaving its run `running`
            # for ever makes every later question about open runs meaningless.
            if trail is not None:
                with suppress(Exception):
                    await trail.failed(run_id, RuntimeError("generation cancelled"))
            raise
        except BaseException as exc:  # noqa: BLE001 - background task boundary
            logger.exception("generation batch %s failed", batch_id)
            if trail is not None:
                with suppress(Exception):
                    await trail.failed(run_id, exc)
            with suppress(Exception):
                await GenerationDraftClient(internal).fail_batch(
                    batch_id, safe_generation_error(exc)
                )
        finally:
            await asyncio.gather(
                data_mcp.cleanup(), internal.cleanup(), return_exceptions=True
            )

    async def _generate_details(
        self,
        batch_id: UUID,
        request: GenerationBatchRequest,
        source_packet: dict[str, Any],
        titles: IdeaTitles,
        base_agent,
        drafts: GenerationDraftClient,
        language: Language = DEFAULT_LANGUAGE,
    ) -> None:
        detail_agent = base_agent.clone(
            model=GENERATION_DETAIL_MODEL,
            output_type=detail_output_type(request.format),
            model_settings=ModelSettings(
                reasoning={"effort": "minimal"},
                verbosity="low",
                max_tokens=24_000,
            ),
        )
        slot_count = min(GENERATION_CONCURRENCY, len(titles.ideas))
        created = await asyncio.gather(
            *(self._create_slot(detail_agent) for _ in range(slot_count)),
            return_exceptions=True,
        )
        slots = [item for item in created if not isinstance(item, BaseException)]
        failures = [item for item in created if isinstance(item, BaseException)]
        if failures:
            await asyncio.gather(
                *(slot[2].aclose() for slot in slots), return_exceptions=True
            )
            raise RuntimeError(
                f"only {len(slots)}/{slot_count} sandbox slots were created"
            ) from failures[0]
        queue: asyncio.Queue[IdeaTitle] = asyncio.Queue()
        for idea in titles.ideas:
            queue.put_nowait(idea)

        async def consume(slot) -> None:
            agent, client, sandbox = slot
            while True:
                try:
                    idea = queue.get_nowait()
                except asyncio.QueueEmpty:
                    return
                # Checked per idea, not only per batch: without this, an account
                # at 95% would spend a whole batch of ten detail calls. Stopping
                # here leaves the ideas already written, and the batch reports
                # the rest as failed rather than pretending they succeeded.
                if self._accounts is not None:
                    await self._accounts.require_budget()
                await self._generate_one_detail(
                    batch_id,
                    request,
                    source_packet,
                    idea,
                    agent,
                    client,
                    sandbox,
                    drafts,
                    language,
                )

        try:
            await asyncio.gather(*(consume(slot) for slot in slots))
        finally:
            await asyncio.gather(
                *(slot[2].aclose() for slot in slots), return_exceptions=True
            )

    async def _generate_one_detail(
        self,
        batch_id: UUID,
        request: GenerationBatchRequest,
        source_packet: dict[str, Any],
        idea: IdeaTitle,
        agent,
        client,
        sandbox,
        drafts: GenerationDraftClient,
        language: Language = DEFAULT_LANGUAGE,
    ) -> None:
        for attempt in (1, 2):
            await drafts.start_idea(batch_id, idea.ordinal)
            try:
                value = await self._run_on_sandbox(
                    agent,
                    detail_prompt(request, idea, source_packet, language),
                    detail_output_type(request.format),
                    f"{batch_id}-idea-{idea.ordinal}-attempt-{attempt}",
                    client,
                    sandbox,
                    str(batch_id),
                )
                if value.idea_ordinal != idea.ordinal or value.title != idea.title:
                    raise ValueError("detail output changed the persisted idea identity")
                await drafts.complete_idea(batch_id, value)
                return
            except asyncio.CancelledError:
                raise
            except BaseException as exc:  # noqa: BLE001 - per-idea isolation
                logger.exception("idea %s of batch %s failed", idea.ordinal, batch_id)
                retryable = attempt == 1 and retryable_generation_error(exc)
                await drafts.fail_idea(
                    batch_id,
                    idea.ordinal,
                    safe_generation_error(exc),
                    retryable=retryable,
                )
                if not retryable:
                    return
                await asyncio.sleep(2)

    @staticmethod
    async def _create_slot(agent):
        client, options = build_sandbox()
        sandbox = await client.create(options=options)
        return agent.clone(), client, sandbox

    async def _run_isolated(
        self, agent, prompt: str, output_type, label: str, group: str
    ):
        client, options = build_sandbox()
        sandbox = await client.create(options=options)
        try:
            return await self._run_on_sandbox(
                agent, prompt, output_type, label, client, sandbox, group
            )
        finally:
            await sandbox.aclose()

    async def _run_on_sandbox(
        self,
        agent,
        prompt: str,
        output_type,
        label: str,
        client,
        sandbox,
        group: str,
    ):
        result = await asyncio.wait_for(
            Runner.run(
                agent,
                prompt,
                run_config=RunConfig(
                    sandbox=SandboxRunConfig(client=client, session=sandbox),
                    workflow_name=GENERATION_WORKFLOW,
                    group_id=group,
                ),
                max_turns=6,
            ),
            timeout=RUN_TIMEOUT_SECONDS,
        )
        # Metered before the interruption check below, because a run that ends
        # in an unexpected approval request still burned the tokens.
        if self._accounts is not None:
            model = getattr(agent, "model", None)
            await self._accounts.record_run(
                label, model if isinstance(model, str) else MODEL, result
            )

        if result.interruptions:
            # Naming the tools matters: this path is reached only when the model
            # reached for a gated write while producing a structured draft, and
            # which write it was decides whether the prompt or the gate is wrong.
            requested = sorted(
                {
                    getattr(getattr(item, "raw_item", None), "name", None) or "?"
                    for item in result.interruptions
                }
            )
            raise RuntimeError(
                f"structured generation unexpectedly requested approval for: "
                f"{', '.join(requested)}"
            )
        return result.final_output_as(output_type, raise_if_incorrect_type=True)

    async def _get_raw(
        self, principal_id: str, batch_id: UUID
    ) -> dict[str, Any]:
        session_id = self._session_id("generation-read", principal_id, unique=False)
        internal = self._internal_mcp_factory(session_id)
        try:
            await internal.connect()
            raw = await GenerationDraftClient(internal).get(batch_id)
        finally:
            await internal.cleanup()
        self._ensure_owner(raw, principal_id)
        return raw

    async def _cancel_principal_task(self, principal_id: str) -> None:
        batch_id = self._principal_tasks.get(principal_id)
        task = self._tasks.get(batch_id) if batch_id is not None else None
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    def _task_done(
        self, batch_id: UUID, principal_id: str, task: asyncio.Task[None]
    ) -> None:
        self._tasks.pop(batch_id, None)
        if self._principal_tasks.get(principal_id) == batch_id:
            self._principal_tasks.pop(principal_id, None)
        with suppress(asyncio.CancelledError):
            task.exception()

    @staticmethod
    def _ensure_owner(batch: dict[str, Any], principal_id: str) -> None:
        if str(batch.get("owner_principal_id")) != principal_id:
            raise GenerationAccessError("Lotul nu aparține contului autentificat.")

    @staticmethod
    def _batch_signature(batch: dict[str, Any]) -> str:
        payload = {
            "status": batch.get("status"),
            "updated_at": batch.get("updated_at"),
            "ideas": [
                {
                    "id": idea.get("id"),
                    "status": idea.get("status"),
                    "updated_at": idea.get("updated_at"),
                    "selected": [
                        item.get("id")
                        for item in idea.get("variants", [])
                        if item.get("is_selected")
                    ],
                }
                for idea in batch.get("ideas", [])
            ],
        }
        return json.dumps(payload, ensure_ascii=False, sort_keys=True)

    @staticmethod
    def _session_id(prefix: str, principal_id: str, *, unique: bool = True) -> str:
        digest = hashlib.sha256(principal_id.encode("utf-8")).hexdigest()[:20]
        suffix = f"-{uuid.uuid4().hex[:8]}" if unique else ""
        return f"{prefix}-{digest}{suffix}"
