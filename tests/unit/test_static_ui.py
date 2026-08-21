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

    def test_a_missing_framework_asset_is_a_404_not_the_page(self) -> None:
        """A stale client must learn the assembly is gone, not receive HTML."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("index", encoding="utf-8")
            app = FastAPI()
            self.assertTrue(mount_ui(app, root))

            with TestClient(app) as client:
                stale_assembly = client.get("/_framework/Studio.oldhash.wasm")

            self.assertEqual(stale_assembly.status_code, 404)

    def test_the_entry_point_is_always_revalidated(self) -> None:
        """index.html names the fingerprints; a cached copy pins an old build."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("index", encoding="utf-8")
            app = FastAPI()
            self.assertTrue(mount_ui(app, root))

            with TestClient(app) as client:
                root_response = client.get("/")
                deep_link = client.get("/profile")

            self.assertEqual(root_response.headers["cache-control"], "no-cache")
            self.assertEqual(deep_link.headers["cache-control"], "no-cache")

    def test_unfingerprinted_files_revalidate_but_fingerprinted_ones_do_not(self) -> None:
        """The stable-named loader holds the fingerprints; it must not be pinned."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("index", encoding="utf-8")
            framework = root / "_framework"
            framework.mkdir()
            (framework / "blazor.webassembly.js").write_text("boot", encoding="utf-8")
            (framework / "App.abcdefghij.wasm").write_bytes(b"assembly")
            styles = root / "css"
            styles.mkdir()
            (styles / "app.css").write_text("body{}", encoding="utf-8")
            app = FastAPI()
            self.assertTrue(mount_ui(app, root))

            with TestClient(app) as client:
                loader = client.get("/_framework/blazor.webassembly.js")
                assembly = client.get("/_framework/App.abcdefghij.wasm")
                stylesheet = client.get("/css/app.css")

            self.assertEqual(loader.status_code, 200)
            self.assertEqual(loader.headers["cache-control"], "no-cache")
            # app.css keeps its name across deployments too, and it is what
            # makes a stale client look merely ugly rather than broken.
            self.assertEqual(stylesheet.status_code, 200)
            self.assertEqual(stylesheet.headers["cache-control"], "no-cache")
            self.assertEqual(assembly.status_code, 200)
            self.assertNotIn("no-cache", assembly.headers.get("cache-control", ""))

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
