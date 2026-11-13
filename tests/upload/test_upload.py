"""`vitra.py upload`: create_upload_url, a PUT to the signed link, then
register_upload. The link is signed over the headers the server returns, so
the PUT must send exactly those; register_upload moves the file to the key it
keeps, so that key (not the upload link's) is the one to hand on. Run from the
repo root:

    python3 -m unittest discover -s tests/upload
"""

from __future__ import annotations

import contextlib
import http.client
import io
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[2] / "brand-kit" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import vitra  # noqa: E402

UPLOAD_URL = "https://bucket.s3.amazonaws.com/org/uploads/abc?X-Amz-Signature=x"
UPLOAD_KEY = "org/uploads/abc"
KEPT_KEY = "org/assets/kept"


class FakeServer:
    """create_upload_url and register_upload answers, and the PUT they lead to."""

    def __init__(self, link: dict, registered: dict) -> None:
        self.link, self.registered = link, registered
        self.tool_calls: list[tuple[str, dict]] = []
        self.puts: list[dict] = []

    def call_tool(self, name: str, args: dict) -> dict:
        self.tool_calls.append((name, args))
        return {"create_upload_url": self.link, "register_upload": self.registered}[name]

    def urlopen(self, req, timeout=None):  # noqa: ANN001
        self.puts.append({"url": req.full_url, "method": req.get_method(),
                          "headers": dict(req.header_items()), "body": req.data.read()})
        return contextlib.nullcontext(SimpleNamespace(status=200))


class UploadTest(unittest.TestCase):
    def upload(self, name: str, data: bytes, link: dict, registered: dict) -> tuple[dict, FakeServer]:
        server = FakeServer({"upload_url": UPLOAD_URL, "key": UPLOAD_KEY, **link}, registered)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / name
            path.write_bytes(data)
            out = io.StringIO()
            with mock.patch.object(vitra, "_call_tool", server.call_tool), \
                    mock.patch.object(vitra.urllib.request, "urlopen", server.urlopen), \
                    mock.patch.dict(os.environ, {"VITRA_SKILLS_NO_UPDATE_CHECK": "1"}), \
                    contextlib.redirect_stdout(out):
                self.assertEqual(vitra.cmd_upload(SimpleNamespace(path=str(path))), 0)
        return json.loads(out.getvalue().strip().splitlines()[-1]), server

    def test_put_sends_exactly_the_headers_the_link_is_signed_over(self) -> None:
        cases = {
            "logo.svg": {"Content-Type": "image/svg+xml",
                         "Content-Disposition": 'attachment; filename="logo.svg"'},
            "page.html": {"Content-Type": "text/html",
                          "Content-Disposition": "attachment"},
            # Header names are case-insensitive: no second Content-Type is added.
            "notes.xhtml": {"content-type": "application/xhtml+xml",
                            "content-disposition": "attachment"},
        }
        for name, signed in cases.items():
            with self.subTest(name):
                _, server = self.upload(name, b"<svg/>", {"headers": signed},
                                        {"asset_id": "a1", "key": KEPT_KEY})
                [put] = server.puts
                self.assertEqual((put["url"], put["method"], put["body"]), (UPLOAD_URL, "PUT", b"<svg/>"))
                want = {k.capitalize(): v for k, v in signed.items()}
                self.assertEqual(put["headers"], {**want, "Content-length": "6"})

    def test_put_sends_the_content_type_when_the_server_gives_no_headers(self) -> None:
        # An older server returns no `headers`, or something that isn't an object.
        for link in ({}, {"headers": None}, {"headers": "Content-Type: image/png"},
                     {"headers": ["Content-Type", "image/png"]}):
            with self.subTest(link):
                _, server = self.upload("banner.png", b"\x89PNG", link,
                                        {"asset_id": "a1", "key": KEPT_KEY})
                [put] = server.puts
                self.assertEqual(put["headers"], {"Content-type": "image/png", "Content-length": "4"})

    def test_put_keeps_its_own_length_and_a_content_type(self) -> None:
        # The real size wins over a stale one, and a signed set without a
        # Content-Type still labels the file (urllib would call it form data).
        _, server = self.upload("deck.pdf", b"%PDF-1", {"headers": {"Content-Length": "999"}},
                                {"asset_id": "a1", "key": KEPT_KEY})
        self.assertEqual(server.puts[0]["headers"],
                         {"Content-length": "6", "Content-type": "application/pdf"})

    def test_hands_on_the_key_register_upload_kept(self) -> None:
        out, server = self.upload("poster.png", b"\x89PNG", {"headers": {"Content-Type": "image/png"}},
                                  {"asset_id": "a1", "key": KEPT_KEY})
        # register_upload is told which upload to keep; the result names the kept key.
        self.assertEqual([n for n, _ in server.tool_calls], ["create_upload_url", "register_upload"])
        self.assertEqual(server.tool_calls[1][1]["key"], UPLOAD_KEY)
        self.assertEqual(out["key"], KEPT_KEY)
        self.assertEqual(out["asset"]["asset_id"], "a1")

    def test_hands_on_the_upload_key_when_register_upload_names_none(self) -> None:
        # An older server keeps the file where it was uploaded.
        for registered in ({"asset_id": "a1"}, {"asset_id": "a1", "key": ""},
                           {"asset_id": "a1", "key": None}, {"asset_id": "a1", "key": 7}):
            with self.subTest(registered):
                out, _ = self.upload("poster.png", b"\x89PNG", {}, registered)
                self.assertEqual(out["key"], UPLOAD_KEY)

    def test_a_header_that_cannot_be_sent_fails_in_one_json_line(self) -> None:
        server = FakeServer({"upload_url": UPLOAD_URL, "key": UPLOAD_KEY,
                             "headers": {"Content-Type": "image/png\r\nX-Injected: 1"}}, {})
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "banner.png"
            path.write_bytes(b"\x89PNG")
            out = io.StringIO()
            # The real urlopen: http.client refuses the header before connecting
            # (and a connection would fail the test, never reach the network).
            with mock.patch.object(vitra, "_call_tool", server.call_tool), \
                    mock.patch.object(http.client.HTTPSConnection, "connect",
                                      side_effect=AssertionError("connected")), \
                    contextlib.redirect_stdout(out), contextlib.redirect_stderr(io.StringIO()), \
                    self.assertRaises(SystemExit) as exit_:
                vitra.cmd_upload(SimpleNamespace(path=str(path)))
        self.assertEqual(exit_.exception.code, 4)
        failed = json.loads(out.getvalue().strip().splitlines()[-1])
        self.assertEqual((failed["status"], failed["error"]["retryable"]), ("failed", False))
        self.assertEqual([n for n, _ in server.tool_calls], ["create_upload_url"])


if __name__ == "__main__":
    unittest.main()
