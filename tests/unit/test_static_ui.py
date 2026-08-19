"""SPA fallback contracts for the published Blazor application."""

import tempfile
import unittest
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from content_studio.harness.static_ui import mount_ui


class TestStaticUi(unittest.TestCase):
    def test_client_route_falls_back_but_unknown_api_does_not(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text(
                "<title>Studio Viorela</title>", encoding="utf-8"
            )
            app = FastAPI()

            @app.get("/api/ping")
            async def ping() -> dict:
                return {"ok": True}

            self.assertTrue(mount_ui(app, root))
            with TestClient(app) as client:
                deep_link = client.get("/profile")
                unknown_api = client.get("/api/unknown")

            self.assertEqual(deep_link.status_code, 200)
            self.assertIn("Studio Viorela", deep_link.text)
            self.assertEqual(unknown_api.status_code, 404)

    def test_prefers_brotli_and_preserves_the_original_content_type(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("index", encoding="utf-8")
            (root / "app.wasm").write_bytes(b"plain")
            (root / "app.wasm.br").write_bytes(b"brotli")
            (root / "app.wasm.gz").write_bytes(b"gzip")
            app = FastAPI()
            self.assertTrue(mount_ui(app, root))

            with TestClient(app) as client:
                response = client.head(
                    "/app.wasm",
                    headers={"Accept-Encoding": "gzip, deflate, br"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-encoding"], "br")
            self.assertEqual(response.headers["content-length"], "6")
            self.assertEqual(response.headers["content-type"], "application/wasm")
            self.assertIn("Accept-Encoding", response.headers["vary"])

    def test_uses_gzip_when_brotli_is_unavailable_to_the_client(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("index", encoding="utf-8")
            (root / "site.css").write_bytes(b"plain")
            (root / "site.css.br").write_bytes(b"brotli")
            (root / "site.css.gz").write_bytes(b"gzip")
            app = FastAPI()
            self.assertTrue(mount_ui(app, root))

            with TestClient(app) as client:
                response = client.head(
                    "/site.css",
                    headers={"Accept-Encoding": "br;q=0, gzip"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.headers["content-encoding"], "gzip")
            self.assertEqual(response.headers["content-length"], "4")
            self.assertEqual(response.headers["content-type"], "text/css")

    def test_serves_plain_asset_when_compression_is_not_accepted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("index", encoding="utf-8")
            (root / "app.js").write_bytes(b"plain")
            (root / "app.js.br").write_bytes(b"brotli")
            app = FastAPI()
            self.assertTrue(mount_ui(app, root))

            with TestClient(app) as client:
                response = client.get(
                    "/app.js",
                    headers={"Accept-Encoding": "identity"},
                )

            self.assertEqual(response.status_code, 200)
            self.assertNotIn("content-encoding", response.headers)
            self.assertEqual(response.content, b"plain")


if __name__ == "__main__":
    unittest.main()
