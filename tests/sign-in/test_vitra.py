"""vitra.py, the forwarder every skill uses: it only relays to the server's
tools route, and never advises retrying a call that may have changed something."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.dont_write_bytecode = True
SCRIPT = Path(__file__).resolve().parents[2] / "brand-kit" / "scripts" / "vitra.py"


class Fake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict, dict]] = []
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _send(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                fake.calls.append(("GET", self.path, {}, dict(self.headers)))
                self._send(200, {"tools": [
                    {"name": "rename_dub", "title": "Rename a dub", "description": "Renames.",
                     "read_only": False, "input_schema": {"type": "object"}},
                    {"name": "get_credits", "title": "Credit balance", "description": "Balance.",
                     "read_only": True, "input_schema": {"type": "object"}}]})

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                body = json.loads(self.rfile.read(n) or b"{}")
                fake.calls.append(("POST", self.path, body, dict(self.headers)))
                if self.path.endswith("/start_dub"):
                    return self._send(402, {"message": "Not enough credits.",
                                            "required": 30, "available": 5, "owed": 0})
                if self.path.endswith("/boom"):
                    return self._send(500, {"message": "Vitra could not finish that."})
                self._send(200, {"name": body["args"].get("name"), "next_action": "done"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


class VitraTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = Fake()
        self.env = {**os.environ, "VITRA_UNIVERSE_BASE_URL": self.fake.base,
                    "VITRA_UNIVERSE_API_KEY": "uvk_test", "VITRA_HOME": tempfile.mkdtemp()}

    def tearDown(self) -> None:
        self.fake.httpd.shutdown()

    def run_cli(self, *args: str) -> dict:
        p = subprocess.run([sys.executable, str(SCRIPT), *args], env=self.env,
                           capture_output=True, text=True, timeout=60)
        return json.loads(p.stdout.strip().splitlines()[-1])

    def test_finds_and_describes_tools(self) -> None:
        out = self.run_cli("tools", "--find", "rename")
        self.assertEqual([t["name"] for t in out["tools"]], ["rename_dub"])
        self.assertTrue(out["tools"][0]["changes_something"])
        self.assertEqual(self.run_cli("describe", "get_credits")["arguments"], {"type": "object"})

    def test_call_forwards_args_intent_and_toolsets(self) -> None:
        out = self.run_cli("call", "rename_dub", '{"name": "Q3 launch"}', "--intent", "tidy",
                           "--toolsets", "hyperlocal_send")
        self.assertEqual(out["result"]["name"], "Q3 launch")
        method, path, body, headers = self.fake.calls[-1]
        self.assertEqual((method, path), ("POST", "/v1/agent/tools/rename_dub"))
        self.assertEqual(body, {"args": {"name": "Q3 launch"}, "user_intent": "tidy"})
        self.assertEqual({k.lower(): v for k, v in headers.items()}.get("x-mcp-toolsets"), "hyperlocal_send")

    def test_failures_keep_facts_and_never_invite_a_blind_retry(self) -> None:
        out = self.run_cli("call", "start_dub", "{}")
        self.assertEqual(out["error"]["code"], "INSUFFICIENT_CREDITS")
        self.assertEqual((out["error"]["required"], out["error"]["available"]), (30, 5))
        self.assertFalse(self.run_cli("call", "boom", "{}")["error"]["retryable"])
        self.assertEqual(self.run_cli("call", "x", "[1]")["error"]["code"], "BAD_ARGUMENTS")


    def test_download_into_a_folder_that_does_not_exist_yet(self) -> None:
        import http.server, ssl  # noqa: E401
        out = self.run_cli("download", "http://example.com/a.png", "--to", "x/")
        self.assertIn("https", out["error"]["message"])
        self.assertNotIn("from Vitra", out["error"]["message"])  # not a promise it can't keep
        sys.path.insert(0, str(SCRIPT.parent))
        import vitra  # noqa: E402
        link = "https://bucket.s3.amazonaws.com/org/7f3a/abc?response-content-disposition=" \
               "attachment%3B%20filename%3D%22Hindi%20dub.mp4%22&X-Amz-Signature=x"
        self.assertEqual(vitra._link_file_name(__import__("urllib.parse").parse.urlsplit(link)),
                         "Hindi dub.mp4")
        self.assertEqual(vitra._link_file_name(__import__("urllib.parse").parse.urlsplit(
            "https://h/path/poster-fr.png?sig=1")), "poster-fr.png")
        self.assertEqual(vitra._link_file_name(__import__("urllib.parse").parse.urlsplit(
            "https://h/x?response-content-disposition=attachment%3Bfilename%3D..%2F..%2Fetc%2Fpasswd")),
            "passwd")

    def test_upload_reads_the_length_an_mp4_declares(self) -> None:
        sys.path.insert(0, str(SCRIPT.parent))
        import vitra  # noqa: E402

        def box(kind: bytes, body: bytes) -> bytes:
            return (8 + len(body)).to_bytes(4, "big") + kind + body

        def mvhd(version: int, scale: int, length: int) -> bytes:
            if version == 1:
                times = bytes(16) + scale.to_bytes(4, "big") + length.to_bytes(8, "big")
            else:
                times = bytes(8) + scale.to_bytes(4, "big") + length.to_bytes(4, "big")
            return box(b"mvhd", bytes([version, 0, 0, 0]) + times + bytes(80))

        ftyp = box(b"ftyp", b"isom" + bytes(4) + b"isommp41")
        # A media box with a 64-bit size before moov, as a camera writes it.
        mdat = (1).to_bytes(4, "big") + b"mdat" + (16 + 64).to_bytes(8, "big") + bytes(64)
        cases = {
            "a.mp4": (ftyp + box(b"moov", mvhd(0, 1000, 56040)), 56.04),
            "b.MOV": (ftyp + mdat + box(b"moov", box(b"udta", b"") + mvhd(1, 600, 1800)), 3.0),
            "c.m4a": (ftyp + box(b"moov", mvhd(0, 44100, 0xFFFFFFFF)), None),  # unknown
            "d.mp4": (ftyp + box(b"moov", b"\x00\x00"), None),  # truncated
            "e.mp4": (b"not an mp4 at all", None),
            "f.webm": (ftyp + box(b"moov", mvhd(0, 1000, 5000)), None),  # not read
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name, (data, want) in cases.items():
                path = Path(tmp) / name
                path.write_bytes(data)
                self.assertEqual(vitra._media_seconds(path), want, name)


if __name__ == "__main__":
    unittest.main()
