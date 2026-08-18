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


if __name__ == "__main__":
    unittest.main()
