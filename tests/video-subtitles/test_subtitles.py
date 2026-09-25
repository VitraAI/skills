"""video-subtitles against a small fake Vitra API: what each script sends and
what it tells the agent. Run from the repo root:

    python3 -m unittest discover -s tests/video-subtitles
"""

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
from urllib.parse import parse_qs, urlparse

sys.dont_write_bytecode = True
SCRIPTS = Path(__file__).resolve().parents[2] / "video-subtitles" / "scripts"
TV = "/v1/galaxy/translate-video"
PL = TV + "/process-log"
JOB = "33333333-3333-4333-8333-333333333333"


class Fake:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object]] = []
        self.tms = [{"id": "tm1", "name": "Acme", "provider": "vitratm", "target_languages": ["hindi"]}]
        self.uploads = 0
        self.children: list[dict] = []
        self.cards = [
            {"id": "c1", "english": {"subs": [
                {"id": "s1", "t": {"st": 0, "et": 1.5}, "text": "<p>Hello &amp; welcome<br>to Vitra</p>"},
                {"id": "s2", "t": {"st": 1.5, "et": 3}, "text": "Second line"}]}},
            {"id": "c2", "english": {"subs": [
                {"id": "s3", "t": {"st": 3, "et": 4}, "text": "Third"}]}},
        ]
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

            def _body(self):
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                if "multipart" in (self.headers.get("Content-Type") or ""):
                    return raw
                return json.loads(raw or b"{}")

            def do_GET(self) -> None:
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                fake.calls.append(("GET", url.path, q))
                if url.path == "/v1/translation-memory":
                    return self._send(200, {"data": fake.tms})
                if url.path == "/v1/language":
                    return self._send(200, [])
                if url.path == f"{TV}/upload":
                    return self._send(200, {"data": []})
                if url.path == f"{PL}/{JOB}/status":
                    return self._send(200, {"status": "completed", "processType": "VIDEO_TO_SUBTITLE",
                                            "sourceLanguage": "english", "targetLanguages": [],
                                            "progress": 100, "progressSteps": {"percent": 100, "summary": "Done"}})
                if url.path == f"{PL}/{JOB}/editor-output":
                    return self._send(200, {"data": {"data": {"OUTPUT": [{"transcripts": fake.cards}]}}})
                if url.path == f"{PL}/x1/editor-output":
                    return self._send(200, {"data": {"data": {"OUTPUT": [{"video": "https://x/v.mp4"}]}}})
                if url.path == f"{PL}/{JOB}/pending-children":
                    return self._send(200, {"data": fake.children})
                if url.path == f"{PL}/{JOB}/subtitle-download":
                    return self._send(200, {"file": {"content": "1\n00:00:00,000 --> 00:00:01,500\nHello\n"},
                                            "subtitles": [{}]})
                return self._send(404, {"message": f"no route {url.path}"})

            def do_POST(self) -> None:
                path = urlparse(self.path).path
                body = self._body()
                fake.calls.append(("POST", path, body))
                if path == f"{TV}/upload":
                    fake.uploads += 1
                    return self._send(201, {"uploads": [{"id": f"u{fake.uploads}"}]})
                if path == f"{PL}/publish":
                    return self._send(201, {"processId": JOB})
                if path == f"{PL}/subtitle/action":
                    return self._send(200, {"success": True})
                if path == f"{PL}/{JOB}/add-languages":
                    fake.children = [{"id": f"k{i}", "operation": "ADD_SUBTITLE_LANGUAGE",
                                      "language": x["targetLanguage"], "status": "DONE"}
                                     for i, x in enumerate(body["languages"])]
                    return self._send(201, {"accepted": [{"id": c["id"], "targetLanguage": c["language"]}
                                                         for c in fake.children]})
                if path == f"{PL}/export-video":
                    return self._send(201, {"data": {"id": "x1"}})
                return self._send(404, {"message": f"no route {path}"})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def sent(self, path: str) -> list:
        return [b for m, p, b in self.calls if m == "POST" and p == path]


class SubtitlesTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = Fake()
        self.addCleanup(self.fake.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)
        self.video = self.dir / "talk.mp4"
        self.video.write_bytes(b"\x00\x00\x00\x18ftypmp42")

    def run_script(self, name: str, *args: str) -> tuple[int, dict]:
        env = {**os.environ, "VITRA_UNIVERSE_API_KEY": "uvk_test", "VITRA_UNIVERSE_BASE_URL": self.fake.base,
               "PYTHONDONTWRITEBYTECODE": "1", "VITRA_DUB_FAST_POLL": "1"}
        proc = subprocess.run([sys.executable, str(SCRIPTS / f"{name}.py"), *args],
                              capture_output=True, text=True, env=env, timeout=60)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertLessEqual(len(lines), 1, proc.stdout)
        return proc.returncode, (json.loads(lines[0]) if lines else {})

    def test_several_memories_are_a_question_asked_before_uploading(self) -> None:
        self.fake.tms.append({"id": "tm2", "name": "Beta", "provider": "vitratm", "target_languages": []})
        code, out = self.run_script("start_subtitles", "--file", str(self.video), "--source-language", "english")
        self.assertNotEqual(code, 0)
        self.assertEqual(out["error"]["code"], "TM_CHOICE_NEEDED")
        self.assertEqual(self.fake.uploads, 0)

    def test_a_subtitle_file_needs_its_target_languages(self) -> None:
        srt = self.dir / "talk.srt"
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\nHi\n")
        code, out = self.run_script("start_subtitles", "--file", str(srt), "--source-language", "english")
        self.assertEqual(out["error"]["code"], "TARGET_LANGUAGE_NEEDED")

    def test_video_with_script_is_published_with_both_uploads(self) -> None:
        script = self.dir / "talk.txt"
        script.write_text("Hello and welcome to Vitra")
        code, out = self.run_script("start_subtitles", "--file", str(self.video), "--source-language", "english",
                                    "--script", str(script))
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["mode"], out["memory"]), ("review_ready", "generate", "Acme"))
        body = self.fake.sent(f"{PL}/publish")[0]
        self.assertEqual((body["processType"], body["uploadIds"], body["tmId"]),
                         ("VIDEO_TO_SUBTITLE", ["u1", "u2"], "tm1"))

    def test_lines_are_numbered_plain_text_without_ids(self) -> None:
        code, out = self.run_script("inspect_subtitles", "--job-id", JOB, "--lines", "english", "--limit", "2")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["lines"][0], {"line": 1, "start": 0, "end": 1.5, "text": "Hello & welcome\nto Vitra"})
        self.assertEqual((out["lines_total"], out["more"]), (3, "--lines english --offset 2"))
        self.assertNotIn("s1", json.dumps(out))
        self.assertNotIn("None", json.dumps(out["suggestions"]))
        self.assertEqual(out["progress"], {"percent": 100, "summary": "Done"})

    def test_an_edit_sends_plain_intent(self) -> None:
        code, out = self.run_script("edit_subtitles", "--job-id", JOB, "--language", "english",
                                    "--edits", json.dumps([{"line": 2, "text": "A < B"}]))
        self.assertEqual(code, 0, out)
        sent = self.fake.sent(f"{PL}/subtitle/action")[0]
        self.assertEqual(sent["data"], {"path": {"language": "english", "transcriptId": "c1", "subtitleId": "s2"},
                                        "subtitle": {"text": "A &lt; B"}})
        self.assertEqual(out["changes"], [{"line": 2, "field": "text", "before": "Second line", "after": "A < B"}])

    def test_only_neighbouring_lines_of_one_passage_merge(self) -> None:
        code, out = self.run_script("edit_subtitles", "--job-id", JOB, "--language", "english", "--merge", "2,3")
        self.assertNotEqual(code, 0)
        self.assertEqual(self.fake.sent(f"{PL}/subtitle/action"), [])

    def test_languages_are_added_in_one_batch(self) -> None:
        code, out = self.run_script("add_subtitle_language", "--job-id", JOB,
                                    "--language", "hindi_india", "--language", "tamil_india")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["added"], ["hindi_india", "tamil_india"])
        self.assertEqual(self.fake.sent(f"{PL}/{JOB}/add-languages")[0],
                         {"languages": [{"targetLanguage": "hindi_india"}, {"targetLanguage": "tamil_india"}],
                          "subtitles": True})

    def test_burn_in_renders_the_original_with_one_language(self) -> None:
        code, out = self.run_script("burn_subtitles", "--job-id", JOB, "--language", "english")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["media_url"], "https://x/v.mp4")
        body = self.fake.sent(f"{PL}/export-video")[0]
        self.assertEqual({k: body[k] for k in ("videoLanguage", "subtitleOnly", "embedSubtitle",
                                               "subtitleLanguage", "lipSync")},
                         {"videoLanguage": "english", "subtitleOnly": True, "embedSubtitle": True,
                          "subtitleLanguage": "english", "lipSync": False})
        self.assertEqual(self.fake.sent(f"{PL}/subtitle/action"), [], "the API seeds any missing style")

    def test_download_writes_the_file(self) -> None:
        out_file = self.dir / "en.srt"
        code, out = self.run_script("download_subtitles", "--job-id", JOB, "--language", "english",
                                    "--out", str(out_file))
        self.assertEqual(code, 0, out)
        self.assertTrue(out_file.read_text().startswith("1\n00:00:00,000"))


if __name__ == "__main__":
    unittest.main()
