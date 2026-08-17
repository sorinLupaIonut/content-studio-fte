"""FastAPI entry point for the Content Studio control plane."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse

from content_studio.config import HARNESS_HOST, HARNESS_PORT
from content_studio.harness.models import (
    DecisionsRequest,
    HealthResponse,
    PendingResponse,
    RunRequest,
    RunResponse,
)
from content_studio.harness.service import HarnessError, HarnessService


def create_app(
    service_factory: Callable[[], HarnessService] = HarnessService,
) -> FastAPI:
    service = service_factory()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.harness = service
        await service.start()
        try:
            yield
        finally:
            await service.close()

    app = FastAPI(title="Content Studio Harness", version="0.1.0", lifespan=lifespan)

    @app.exception_handler(HarnessError)
    async def harness_error(_request: Request, exc: HarnessError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})

    @app.get("/health", response_model=HealthResponse)
    async def health(request: Request) -> HealthResponse:
        return await request.app.state.harness.health()

    @app.post("/runs", response_model=RunResponse)
    async def create_run(body: RunRequest, request: Request, response: Response) -> RunResponse:
        result = await request.app.state.harness.run(body.message, body.session_id)
        if result.status == "pending":
            response.status_code = 202
        return result

    @app.get("/sessions/{session_id}/pending", response_model=PendingResponse)
    async def pending(session_id: str, request: Request) -> PendingResponse:
        return await request.app.state.harness.pending(session_id)

    @app.post("/runs/{run_id}/decisions", response_model=RunResponse)
    async def decide(
        run_id: str,
        body: DecisionsRequest,
        request: Request,
        response: Response,
    ) -> RunResponse:
        result = await request.app.state.harness.decide(
            run_id, body.session_id, body.decisions, body.resolved_by
        )
        if result.status == "pending":
            response.status_code = 202
        return result

    return app


app = create_app()


def run() -> None:
    """Console entry point used locally; Azure supplies the same host and port."""
    import uvicorn

    uvicorn.run("content_studio.harness.main:app", host=HARNESS_HOST, port=HARNESS_PORT)
