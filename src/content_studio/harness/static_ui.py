"""Serve the published Blazor application without shadowing API routes."""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path

from fastapi import FastAPI
from starlette.exceptions import HTTPException
from starlette.responses import Response
from starlette.staticfiles import StaticFiles

# Python's table knows neither web font format, and Starlette answers an unknown
# extension with text/plain. Registered here rather than assumed, because on
# Windows `mimetypes` reads the system registry first and that differs between
# machines - so the local answer is not evidence about the container's.
mimetypes.add_type("font/woff2", ".woff2")
mimetypes.add_type("font/woff", ".woff")


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


# Publishing fingerprints most assets - `StudioViorela.pgjknfelkv.wasm` - and
# those may be cached forever, because a new build means a new name. The rest
# keep stable names across deployments: index.html, app.css, and the loader
# chain that holds the fingerprints. Cached, those pin a browser to an old
# build indefinitely - it keeps asking for assemblies that no longer exist and
# never learns anything shipped. Anything unfingerprinted is revalidated.
# The fingerprint is exactly ten base-36 characters, inserted before the
# extension. Ten is what separates it from an ordinary compound name:
# `blazor.webassembly.js` carries eleven and must never be treated as
# fingerprinted, since it is the file that lists all the others.
_FINGERPRINTED = re.compile(r"\.[a-z0-9]{10}\.[^.]+$")


def _is_fingerprinted(path: str) -> bool:
    """Whether the name changes with the content, making the file immutable."""
    return _FINGERPRINTED.search(path.rsplit("/", 1)[-1]) is not None


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

    async def _entry_point(self, scope) -> Response:
        """Serve index.html, always revalidated.

        The published client is fingerprinted, so every asset but this one may
        be cached forever. index.html carries the list of those fingerprints:
        cached, it keeps asking for the assemblies of a deployment that is gone,
        and the client stays on an old build long after a release.
        """
        response = await self._asset_response("index.html", scope)
        response.headers["Cache-Control"] = "no-cache"
        return response

    def _is_spa_route(self, scope) -> bool:
        """Only client routes fall back to index.html; assets must 404.

        A missing asset answered with HTML is a 200 that lies. A stale client
        asking for a deleted assembly would receive the page instead of a clean
        cache miss, and fail somewhere far from the cause.
        """
        request_path = str(scope.get("path", ""))
        return not any(
            request_path.startswith(prefix)
            for prefix in ("/api/", "/_framework/", "/_content/")
        )

    async def get_response(self, path: str, scope):
        fallback = self._is_spa_route(scope)
        try:
            response = await self._asset_response(path, scope)
        except HTTPException as exc:
            if exc.status_code != 404 or not fallback:
                raise
            return await self._entry_point(scope)
        if response.status_code == 404 and fallback:
            return await self._entry_point(scope)
        # Starlette normalises with the platform separator, so this comparison
        # has to be made on forward slashes or it silently never matches on
        # Windows. The mount root arrives as "." rather than an empty string.
        relative = path.replace("\\", "/")
        if not _is_fingerprinted(relative):
            response.headers["Cache-Control"] = "no-cache"
        return response


def mount_ui(app: FastAPI, static_dir: Path) -> bool:
    """Mount an existing publish output; development can boot without it."""
    if not (static_dir / "index.html").is_file():
        return False
    app.mount("/", BlazorStaticFiles(directory=static_dir, html=True), name="ui")
    return True
