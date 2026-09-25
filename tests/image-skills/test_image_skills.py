"""Image skills against a small fake Vitra API: the upload route, the memory
rules and the access check. Run from the repo root:

    python3 -m unittest discover -s tests/image-skills
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zlib
import struct
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
ADAPT = "/v1/galaxy/translate-photo/adapt"


def tiny_png() -> bytes:
    raw = b"".join(b"\x00" + b"\xff\x00\x00" * 4 for _ in range(4))

    def chunk(t: bytes, d: bytes) -> bytes:
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)

    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", 4, 4, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw)) + chunk(b"IEND", b""))


class Fake:
    """Records every call; answers the routes these skills use."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, bytes]] = []
        self.variant_polls = 0
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def _send(self, status: int, payload) -> None:
                body = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

            def _body(self) -> bytes:
                n = int(self.headers.get("Content-Length") or 0)
                return self.rfile.read(n) if n else b""

            def do_PUT(self) -> None:
                fake.calls.append(("PUT", urlparse(self.path).path, self._body()))
                self._send(500, {"message": "no direct storage uploads expected"})

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                body = self._body()
                fake.calls.append(("POST", path, body))
                if path == "/v1/assets-management/multi-upload":
                    return self._send(201, [{"key": "org-1/abc.png", "url": "https://x/abc.png", "error": None}])
                if path == f"{ADAPT}/assets":
                    return self._send(201, {"id": json.loads(body)["designAssetId"]})
                if path.startswith(ADAPT) and path.endswith("/adapt"):
                    return self._send(201, {"ok": True})
                if path == "/v1/translation-memory":
                    return self._send(201, {"id": "tm-new"})
                return self._send(404, {"message": f"no route {path}"})

            def do_GET(self) -> None:
                path = urlparse(self.path).path
                fake.calls.append(("GET", path, b""))
                if path.startswith(ADAPT) and path.endswith("/variants"):
                    fake.variant_polls += 1
                    done = fake.variant_polls >= 2
                    return self._send(200, {"data": [{
                        "variantCategory": "Banner", "targetConfig": {"width": 128, "height": 64},
                        "status": "completed" if done else "processing",
                        "generatedImageUrl": "https://x/v.png" if done else None}]})
                if path == "/v1/translation-memory":
                    return self._send(200, {"data": []})
                return self._send(404, {"message": f"no route {path}"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()


class ImageSkillsTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = Fake()
        self.addCleanup(self.fake.close)
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.png = Path(self.tmp.name) / "banner.png"
        self.png.write_bytes(tiny_png())

    def run_script(self, skill: str, name: str, *args: str) -> tuple[int, dict]:
        env = {**os.environ, "VITRA_UNIVERSE_API_KEY": "uvk_test",
               "VITRA_UNIVERSE_BASE_URL": self.fake.base, "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, str(ROOT / skill / "scripts" / f"{name}.py"), *args],
                              capture_output=True, text=True, env=env, timeout=60)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        return proc.returncode, (json.loads(lines[-1]) if lines else {})

    def test_resize_uploads_through_the_api_and_adopts_by_key(self) -> None:
        code, out = self.run_script("image-resize", "resize_image", "--file", str(self.png),
                                    "--size", "128x64=Banner", "--poll-interval", "0")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["outputs"][0]["image_url"], "https://x/v.png")
        self.assertFalse([c for c in self.fake.calls if c[0] == "PUT"], "no direct storage PUT")
        asset = next(json.loads(b) for m, p, b in self.fake.calls if p == f"{ADAPT}/assets")
        self.assertEqual(asset["sourceKey"], "org-1/abc.png")
        self.assertNotIn("objectUrl", asset)

    def test_new_memory_asks_for_its_context_first(self) -> None:
        code, out = self.run_script("image-translation", "translate_image", "--file", str(self.png),
                                    "--target-language", "French", "--create-tm")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "TM_CONTEXT_NEEDED")
        self.assertIn("Who will this translation memory be for", out["error"]["ask"])
        self.assertEqual(self.fake.calls, [], "stops before touching the API")

    def test_new_memory_sends_context_and_engine(self) -> None:
        self.run_script("image-translation", "translate_image", "--file", str(self.png),
                        "--target-language", "French", "--create-tm",
                        "--tm-context", "Acme posters for shoppers in France", "--tm-engine", "azure")
        created = next(json.loads(b) for m, p, b in self.fake.calls
                       if m == "POST" and p == "/v1/translation-memory")
        self.assertEqual(created["context"], "Acme posters for shoppers in France")
        self.assertEqual(created["engine"], "azure")

    def test_every_skill_has_an_access_check(self) -> None:
        for skill in ("image-creator", "image-resize", "image-translation", "video-dubbing", "video-subtitles"):
            code, out = self.run_script(skill, "check_access")
            self.assertEqual((code, out["status"]), (0, "unknown"), skill)


if __name__ == "__main__":
    unittest.main()
