"""Serve the published Blazor application without shadowing API routes."""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.staticfiles import StaticFiles


class BlazorStaticFiles(StaticFiles):
    """Return the SPA entry point for client-side routes."""

    async def get_response(self, path: str, scope):
        is_api = str(scope.get("path", "")).startswith("/api/")
        try:
            response = await super().get_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or is_api:
                raise
            return await super().get_response("index.html", scope)
        if response.status_code == 404 and not is_api:
            return await super().get_response("index.html", scope)
        return response


def mount_ui(app: FastAPI, static_dir: Path) -> bool:
    """Mount an existing publish output; development can boot without it."""
    if not (static_dir / "index.html").is_file():
        return False
    app.mount("/", BlazorStaticFiles(directory=static_dir, html=True), name="ui")
    return True
