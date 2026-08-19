"""Serve the published Blazor application without shadowing API routes."""

from __future__ import annotations

import mimetypes
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles


def _accepted_encodings(scope) -> set[str]:
    """Return content codings accepted with a non-zero quality value."""
    header = next(
        (
            value.decode("latin-1")
            for name, value in scope.get("headers", [])
            if name.lower() == b"accept-encoding"
        ),
        "",
    )
    accepted: set[str] = set()
    for item in header.split(","):
        name, *parameters = (part.strip().lower() for part in item.split(";"))
        if not name:
            continue
        quality = 1.0
        for parameter in parameters:
            if not parameter.startswith("q="):
                continue
            try:
                quality = float(parameter[2:])
            except ValueError:
                quality = 0.0
        if quality > 0:
            accepted.add(name)
    return accepted


def _mark_encoded(response: Response, path: str, encoding: str) -> Response:
    """Describe the original asset while sending its precompressed bytes."""
    content_type, _ = mimetypes.guess_type(path)
    if content_type:
        response.headers["Content-Type"] = content_type
    response.headers["Content-Encoding"] = encoding
    vary = {value.strip() for value in response.headers.get("Vary", "").split(",")}
    vary.discard("")
    vary.add("Accept-Encoding")
    response.headers["Vary"] = ", ".join(sorted(vary))
    return response


class BlazorStaticFiles(StaticFiles):
    """Serve precompressed assets and the SPA entry point for client routes."""

    async def _asset_response(self, path: str, scope) -> Response:
        accepted = _accepted_encodings(scope)
        candidates = (
            ("br", ".br"),
            ("gzip", ".gz"),
        )
        for encoding, suffix in candidates:
            if encoding not in accepted and "*" not in accepted:
                continue
            try:
                response = await super().get_response(f"{path}{suffix}", scope)
            except HTTPException as exc:
                if exc.status_code == 404:
                    continue
                raise
            if response.status_code != 404:
                return _mark_encoded(response, path, encoding)
        return await super().get_response(path, scope)

    async def get_response(self, path: str, scope):
        is_api = str(scope.get("path", "")).startswith("/api/")
        try:
            response = await self._asset_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or is_api:
                raise
            return await self._asset_response("index.html", scope)
        if response.status_code == 404 and not is_api:
            return await self._asset_response("index.html", scope)
        return response


def mount_ui(app: FastAPI, static_dir: Path) -> bool:
    """Mount an existing publish output; development can boot without it."""
    if not (static_dir / "index.html").is_file():
        return False
    app.mount("/", BlazorStaticFiles(directory=static_dir, html=True), name="ui")
    return True
