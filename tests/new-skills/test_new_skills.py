"""The newer skills against a small fake Vitra API: what each script sends,
what it prints, and that nothing is started twice or sent without a yes.
Run from the repo root:

    python3 -m unittest discover -s tests/new-skills
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
ROOT = Path(__file__).resolve().parents[2]
LANGUAGES = [{"name": "german", "label": "German", "code": "de-DE"},
             {"name": "french", "label": "French", "code": "fr-FR"},
             {"name": "english_united_states", "label": "English (United States)", "code": "en-US"}]
TM_ROWS = [
    {"id": "11111111-1111-4111-8111-111111111111", "name": "Acme", "provider": "vitratm",
     "sourceLanguage": "en-US", "targetLanguages": ["fr-FR", "de-DE"]},
    {"id": "22222222-2222-4222-8222-222222222222", "name": "Beta", "provider": "vitratm",
     "sourceLanguage": "en-US", "targetLanguages": ["fr-FR"]},
]


class Fake:
    """Answers from a route table: (method, path) → payload, or a function of
    the request returning (status, payload) or raw bytes."""

    def __init__(self, routes: dict) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, object]] = []
        fake = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:
                pass

            def _reply(self, method: str) -> None:
                url = urlparse(self.path)
                n = int(self.headers.get("Content-Length") or 0)
                raw = self.rfile.read(n) if n else b""
                ctype = self.headers.get("Content-Type") or ""
                body: object = raw if "multipart" in ctype else (json.loads(raw) if raw else {})
                query = {k: v[0] for k, v in parse_qs(url.query).items()}
                fake.calls.append((method, url.path, body))
                answer = fake.routes.get((method, url.path))
                if answer is None:  # a route ending in "*" matches by prefix
                    answer = next((v for (m, pth), v in fake.routes.items()
                                   if m == method and pth.endswith("*") and url.path.startswith(pth[:-1])), None)
                if answer is None:
                    return self._send(404, {"message": f"no route {method} {url.path}"})
                if callable(answer):
                    answer = answer(body, query)
                if isinstance(answer, bytes):
                    self.send_response(200)
                    self.send_header("Content-Length", str(len(answer)))
                    self.end_headers()
                    self.wfile.write(answer)
                    return None
                status, payload = answer if isinstance(answer, tuple) else (200, answer)
                return self._send(status, payload)

            def _send(self, status: int, payload: object) -> None:
                data = json.dumps(payload).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self) -> None:
                self._reply("GET")

            def do_POST(self) -> None:
                self._reply("POST")

            def do_PUT(self) -> None:
                self._reply("PUT")

            def do_PATCH(self) -> None:
                self._reply("PATCH")

            def do_DELETE(self) -> None:
                self._reply("DELETE")

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def close(self) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    def sent(self, method: str, path: str) -> list:
        return [b for m, p, b in self.calls if m == method and p == path]


class SkillCase(unittest.TestCase):
    routes: dict = {}

    def setUp(self) -> None:
        self.fake = Fake(dict(self.routes))
        self.addCleanup(self.fake.close)
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.dir = Path(tmp.name)

    def run_script(self, skill: str, name: str, *args: str) -> tuple[int, dict]:
        env = {**os.environ, "VITRA_UNIVERSE_API_KEY": "uvk_test", "VITRA_UNIVERSE_BASE_URL": self.fake.base,
               "VITRA_STATE_DIR": str(self.dir / "state"), "VITRA_DUB_FAST_POLL": "1",
               "PYTHONDONTWRITEBYTECODE": "1"}
        proc = subprocess.run([sys.executable, str(ROOT / skill / "scripts" / f"{name}.py"), *args],
                              capture_output=True, text=True, env=env, timeout=60, cwd=self.dir)
        lines = [ln for ln in proc.stdout.splitlines() if ln.strip()]
        self.assertLessEqual(len(lines), 1, f"{name} printed more than one line:\n{proc.stdout}")
        return proc.returncode, (json.loads(lines[0]) if lines else {})


DOC = "/v1/galaxy/playground/document"


class DocumentTranslationTest(SkillCase):
    routes = {
        ("GET", "/v1/translation-memory"): {"data": TM_ROWS},
        ("GET", "/v1/language"): LANGUAGES,
        ("POST", f"{DOC}/translate"): (201, {"id": "log-1", "status": "INPROGRESS"}),
        ("GET", f"{DOC}/logs/log-1"): {"data": {"id": "log-1", "status": "DONE"}},
        ("GET", f"{DOC}/logs/log-1/export"): b"PK-translated-docx",
    }

    def test_several_memories_are_a_question_asked_before_translating(self) -> None:
        doc = self.dir / "c.docx"
        doc.write_bytes(b"PK")
        code, out = self.run_script("document-translation", "translate_document", "--file", str(doc),
                                    "--target-language", "French")
        self.assertEqual(out["error"]["code"], "TM_CHOICE_NEEDED")
        self.assertEqual(self.fake.sent("POST", f"{DOC}/translate"), [])

    def test_a_choice_passed_back_as_shown_picks_that_memory(self) -> None:
        doc = self.dir / "c.docx"
        doc.write_bytes(b"PK")
        _, asked = self.run_script("document-translation", "translate_document", "--file", str(doc),
                                   "--target-language", "French")
        choice = next(c for c in asked["error"]["choices"] if c.startswith("Beta"))
        code, out = self.run_script("document-translation", "translate_document", "--file", str(doc),
                                    "--target-language", "French", "--tm-name", choice,
                                    "--out-dir", str(self.dir / "out"))
        self.assertEqual((code, out["memory"]), (0, "Beta"))
        self.assertIn(b"22222222-2222-4222-8222-222222222222", self.fake.sent("POST", f"{DOC}/translate")[0])

    def test_a_file_is_translated_downloaded_and_never_twice(self) -> None:
        doc = self.dir / "c.docx"
        doc.write_bytes(b"PK")
        args = ("--file", str(doc), "--target-language", "German", "--out-dir", str(self.dir / "out"))
        code, out = self.run_script("document-translation", "translate_document", *args)
        self.assertEqual(code, 0, out)
        self.assertEqual((out["status"], out["memory"]), ("translated", "Acme"))
        self.assertEqual(Path(out["results"][0]["path"]).read_bytes(), b"PK-translated-docx")
        sent = self.fake.sent("POST", f"{DOC}/translate")[0]
        for field in (b'name="tmId"', b"11111111-1111-4111-8111-111111111111", b'name="targetLanguage"',
                      b"de-DE", b'name="format"', b"DOCX", b'name="file"'):
            self.assertIn(field, sent)
        self.run_script("document-translation", "translate_document", *args)
        self.assertEqual(len(self.fake.sent("POST", f"{DOC}/translate")), 1, "reconnects, never re-translates")


PG = "/v1/galaxy/playground"


class SpeechTest(SkillCase):
    def setUp(self) -> None:
        super().setUp()
        self.fake.routes.update({
            ("POST", f"{PG}/tts/generate"): {"id": "line-1", "status": "processing"},
            ("GET", "/audio/clip.mp3"): b"ID3-audio",
        })

        def card(body, query):  # every clip is done, with a presigned link
            return {"status": "done", "outputUrl": f"{self.fake.base}/audio/clip.mp3", "durationSeconds": 2}
        self.cards = card

    def test_clips_exist_before_they_are_generated(self) -> None:
        self.fake.routes[("PUT", f"{PG}/video-process/session/*")] = {"id": "s"}
        self.fake.routes[("GET", f"{PG}/video-process/*")] = self.cards
        code, out = self.run_script("text-to-speech", "speak", "--text", "Hello.\n\nSecond part.",
                                    "--language", "english_united_states", "--voice-id", "v1",
                                    "--provider", "elevenlabs", "--name", "Hi", "--out-dir", str(self.dir))
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out["files"]), 2)
        self.assertNotIn("v1", json.dumps(out), "the voice's id is never shown")

    def test_pronunciations_ride_on_every_clip(self) -> None:
        self.fake.routes[("PUT", f"{PG}/video-process/session/*")] = {"id": "s"}
        self.fake.routes[("GET", f"{PG}/video-process/*")] = self.cards
        code, out = self.run_script("text-to-speech", "speak", "--text", "SQL is fast.", "--language",
                                    "english_united_states", "--voice-id", "v1", "--provider", "elevenlabs",
                                    "--say", "SQL=sequel", "--out-dir", str(self.dir))
        self.assertEqual(code, 0, out)
        cards = [c for _, p, b in self.fake.calls if p.startswith(f"{PG}/video-process/session/") for c in b["cards"]]
        self.assertTrue(cards and all(c["pronunciations"] == [{"match": "SQL", "alias": "sequel"}] for c in cards))
        code, bad = self.run_script("text-to-speech", "speak", "--text", "x", "--language", "english_united_states",
                                    "--voice-id", "v1", "--provider", "elevenlabs", "--say", "SQL")
        self.assertIn("--say takes WORD=HOW", bad["error"]["message"])
        order = [(m, p) for m, p, _ in self.fake.calls if m in ("PUT", "POST")]
        self.assertTrue(order[0][1].startswith(f"{PG}/video-process/session/"), "the session is saved first")
        gens = self.fake.sent("POST", f"{PG}/tts/generate")
        self.assertTrue(all(g.get("cardId") and g.get("sessionId") for g in gens), "every clip names its card")


class VoiceAndLipSyncTest(SkillCase):
    routes = {
        ("POST", f"{PG}/voice-clone"): {"name": "Me", "provider": "elevenlabs", "providerVoiceId": "pv1",
                                        "status": "ready", "previewUrl": "https://x/p.mp3"},
        ("POST", f"{PG}/lip-sync"): {"id": "ls-1", "status": "processing"},
    }

    def test_samples_are_sent_as_files(self) -> None:
        a, b = self.dir / "a.wav", self.dir / "b.wav"
        a.write_bytes(b"RIFF-a")
        b.write_bytes(b"RIFF-b")
        code, out = self.run_script("voice-cloning", "clone_voice", "--sample", str(a), "--sample", str(b),
                                    "--name", "Me")
        self.assertEqual((code, out["status"], out["voice"]["voice_id"]), (0, "ready", "pv1"))
        body = self.fake.sent("POST", f"{PG}/voice-clone")[0]
        self.assertEqual(body.count(b'name="samples"'), 2)

    def test_lip_sync_needs_audio_and_saves_the_render(self) -> None:
        video, audio = self.dir / "v.mp4", self.dir / "a.wav"
        video.write_bytes(b"MP4")
        audio.write_bytes(b"WAV")
        self.fake.routes[("GET", f"{PG}/lip-sync/ls-1")] = {
            "status": "done", "outputUrl": f"{self.fake.base}/v/out.mp4", "durationSeconds": 3}
        self.fake.routes[("GET", "/v/out.mp4")] = b"MP4-synced"
        code, out = self.run_script("lip-sync", "lip_sync", "--video", str(video), "--audio", str(audio),
                                    "--language", "hindi_india", "--out", str(self.dir / "o.mp4"))
        self.assertEqual(code, 0, out)
        self.assertEqual(Path(out["path"]).read_bytes(), b"MP4-synced")
        body = self.fake.sent("POST", f"{PG}/lip-sync")[0]
        self.assertIn(b'name="video"', body)
        self.assertIn(b'name="audio"', body)


TMP = "/v1/translation-memory"


class MemoryAndQualityTest(SkillCase):
    routes = {
        ("GET", TMP): {"data": TM_ROWS},
        ("GET", "/v1/language"): LANGUAGES,
        ("POST", f"{TMP}/translate"): {"status": "ready", "data": [
            {"targetLanguage": "de-DE", "translations": [
                {"sourceText": "Checkout", "targetText": "Kasse", "matchType": "exact", "status": "approved"}]}]},
        ("GET", f"{TMP}/{TM_ROWS[0]['id']}/terms"): {"data": [
            {"sourceText": "Checkout", "targetLanguage": "de-DE", "targetText": "Bezahlen", "status": "verified"}]},
        ("PUT", f"{TMP}/{TM_ROWS[0]['id']}/terms"): {"ok": True},
        ("POST", "/v1/aiqe/reports"): (201, {"id": "r1", "status": "succeeded",
                                             "scorecard": {"score": 82, "band": "good", "passed": True}}),
        ("GET", "/v1/aiqe/reports/r1/segments"): {"data": [
            {"key": "2", "sourceText": "B", "targetText": "b", "score": 40,
             "errors": [{"severity": "major", "category": "accuracy", "explanation": "wrong"}]},
            {"key": "1", "sourceText": "A", "targetText": "a", "score": 90, "errors": []}]},
    }

    def test_strings_come_back_per_language_with_where_they_came_from(self) -> None:
        code, out = self.run_script("translation-memory", "translate_text", "--text", "Checkout",
                                    "--target-language", "German")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["translations"]["de-DE"][0], {"source": "Checkout", "text": "Kasse",
                                                           "match": "exact", "status": "approved"})

    def test_a_correction_shows_before_and_after(self) -> None:
        code, out = self.run_script("translation-memory", "correct_term", "--tm-name", "Acme", "--source-text",
                                    "Checkout", "--target-language", "German", "--target-text", "Kasse")
        self.assertEqual((out["before"], out["after"], out["review"]), ("Bezahlen", "Kasse", "approved"))
        body = self.fake.sent("PUT", f"{TMP}/{TM_ROWS[0]['id']}/terms")[0]
        self.assertEqual(body["previousTargetText"], "Bezahlen")

    def test_quality_lists_the_worst_lines_first(self) -> None:
        pairs = self.dir / "p.csv"
        pairs.write_text("source,translation\nA,a\nB,b\n")
        code, out = self.run_script("translation-quality", "evaluate", "--pairs", str(pairs),
                                    "--source-language", "English (United States)", "--target-language", "German")
        self.assertEqual(code, 0, out)
        self.assertEqual((out["score"], out["passed"], out["lines_with_errors"]), (82, True, 1))
        self.assertEqual(out["worst"][0]["line"], 2)
        sent = self.fake.sent("POST", "/v1/aiqe/reports")[0]
        # names and memory spellings go out as the codes the report takes
        self.assertEqual((sent["sourceLanguage"], sent["targetLanguage"]), ("en-US", "de-DE"))
        self.assertEqual(sent["segments"], [{"key": "1", "source": "A", "target": "a"},
                                            {"key": "2", "source": "B", "target": "b"}])


QC = "/v1/galaxy/quality-control"


class ComplianceTest(SkillCase):
    routes = {
        ("GET", f"{QC}/region"): [{"id": "reg-1", "name": "Germany", "ruleCount": 4}],
        ("POST", f"{QC}/classification/classify-text"): (201, {"jobId": "j1", "status": "queued"}),
        ("GET", f"{QC}/classification/jobs/j1"): {"status": "succeeded", "result": {"decisionId": "d1"}},
        ("GET", f"{QC}/classification/decisions/d1"): {
            "modality": "text", "verdict": "REVIEW", "overallScore": 70, "regions": [{
                "region_name": "Germany", "verdict": "REVIEW", "region_score": 70,
                "per_rule": [{"title": "Price claims", "severity": "high", "score": 30, "rationale": "x"},
                             {"title": "Tone", "severity": "low", "score": 100, "rationale": "ok"}],
                "additional_findings": [{"title": "Slang", "severity": "low", "score": 75, "rationale": "y"}]}]},
    }

    def test_concerns_are_named_worst_first(self) -> None:
        code, out = self.run_script("content-compliance", "check_content", "--text", "Best price ever!",
                                    "--market", "Germany")
        self.assertEqual(code, 0, out)
        self.assertEqual(out["verdict"], "REVIEW")
        self.assertEqual([(c["title"], c["level"]) for c in out["markets"][0]["concerns"]],
                         [("Price claims", "fails"), ("Slang", "caution")])
        self.assertEqual(self.fake.sent("POST", f"{QC}/classification/classify-text")[0]["regionIds"], ["reg-1"])


class GatesTest(SkillCase):
    routes = {
        ("GET", "/v1/cosmos/flows"): [{"id": "f1", "name": "Launch", "inputSchema": [
            {"key": "video", "label": "Video", "type": "media", "required": True}]}],
    }

    def test_a_campaign_is_never_sent_without_a_yes(self) -> None:
        code, out = self.run_script("hyperlocal-campaigns", "send", "--campaign", "b1", "--now")
        self.assertEqual(out["error"]["code"], "CONFIRMATION_NEEDED")
        self.assertEqual(self.fake.calls, [], "stops before touching the API")

    def test_a_workflow_asks_for_its_missing_inputs(self) -> None:
        code, out = self.run_script("workflows", "run_flow", "--flow", "Launch")
        self.assertEqual(out["error"]["code"], "INPUT_NEEDED")
        self.assertIn("Video", out["error"]["ask"])

    def test_only_the_user_decides_a_step(self) -> None:
        code, out = self.run_script("workflows", "decide", "--run", "r1", "--approve", "2")
        self.assertEqual(out["error"]["code"], "CONFIRMATION_NEEDED")


if __name__ == "__main__":
    unittest.main()
