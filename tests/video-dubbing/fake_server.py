"""A small in-memory stand-in for the Universe translate-video API.

Implements just the routes the skill calls, with the behaviours the scripts
depend on: revisions that move on every transcript write and refuse a stale
`expectedRevision` (409 + X-Transcript-Revision), child jobs that finish on
the next poll, audio files whose bytes change when regenerated (same url),
the one-level language-block merge, and an uploadId filter that can be
switched off to imitate an older server.

Tests reach in through `FakeServer.state` to arrange and inspect.
"""

from __future__ import annotations

import copy
import json
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

PL = "/v1/galaxy/translate-video/process-log"
JOB = "11111111-1111-4111-8111-111111111111"
UPLOAD = "22222222-2222-4222-8222-222222222222"


def _mp4(seconds_marker: bytes = b"") -> bytes:
    ftyp = (24).to_bytes(4, "big") + b"ftypisom" + b"\0" * 12
    moov = (16 + 20000).to_bytes(4, "big") + b"moov" + b"\0" * 8 + b"x" * 20000 + seconds_marker
    return ftyp + moov[: 16 + 20000]


def default_state(base: str) -> dict:
    def card(cid, st, et, en, hi, speaker="1", audio=True, rs=None):
        hi_block = {"tr": {"text": hi, "cc": len(hi), "wc": len(hi.split()), "c": 0.9},
                    "v": {"st": st, "et": et, "r": 1}, "subs": [
                        {"id": f"{cid}-s1", "t": {"st": st, "et": (st + et) / 2}, "text": "first half"},
                        {"id": f"{cid}-s2", "t": {"st": (st + et) / 2, "et": et}, "text": "second half"}]}
        if audio:
            hi_block["a"] = {"url": f"{base}/audio/{cid}.wav", "d": et - st, "r": 1.0}
        if rs:
            hi_block["rs"] = rs
        return {"id": cid,
                "english": {"tr": {"text": en, "cc": len(en), "wc": len(en.split())},
                            "v": {"st": st, "et": et}, "speakerId": speaker},
                "hindi": hi_block}

    return {
        "revision": 3,
        "status": "completed",
        "awaiting": False,
        "source": "english",
        "targets": ["hindi"],
        "speakers": {"1": {"english": {"label": "Speaker 1", "gender": "male"},
                           "hindi": {"voiceId": "clone-1", "voiceName": "Speaker 1",
                                     "voiceType": "instant-clone", "gender": "male"}},
                     "2": {"english": {"label": "Speaker 2"}}},
        "cards": [
            card("c1", 0.0, 2.0, "Hello there", "नमस्ते"),
            card("c2", 3.0, 5.0, "How are you", "आप कैसे हैं", rs="a"),
            card("c3", 6.0, 8.0, "Goodbye now", "अलविदा", audio=False),
        ],
        "duration": 10.0,
        "audio": {"c1": b"RIFF0000WAVEone", "c2": b"RIFF0000WAVEtwo"},
        "children": [],
        "issues": {"hindi": {"errors": [], "warnings": []}},
        "upload_filter": True,
        "uploads": [{"id": UPLOAD, "originalName": "talk.mp4", "sha256": "a" * 64,
                     "mediaType": "video", "sizeBytes": 10, "status": "uploaded"}],
        "processes": [{"id": JOB, "processName": "dub", "status": "completed",
                       "sourceLanguage": "english", "targetLanguages": ["hindi"], "upload": UPLOAD}],
        "exports": {},
        "export_should_fail": False,
        "child_outcome": "DONE",
        "on_child_done": None,  # callable(state, child) to apply a job's effect
        "calls": [],
        "credits": 120.5,
        "retry_status": 200,
        "clones": [{"id": "clone-1", "name": "Speaker 1", "status": "ready"}],
    }


class FakeServer:
    def __init__(self) -> None:
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
        self.httpd.fake = self  # type: ignore[attr-defined]
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        self.state = default_state(self.base)
        self.lock = threading.Lock()
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self) -> "FakeServer":
        self.thread.start()
        return self

    def __exit__(self, *exc) -> None:
        self.httpd.shutdown()
        self.httpd.server_close()

    # --- helpers the handler uses -----------------------------------------
    def card(self, cid: str) -> dict | None:
        return next((c for c in self.state["cards"] if c["id"] == cid), None)

    def write(self, expected) -> tuple[int, dict]:
        """A guarded transcript write: bump the revision or refuse."""
        if expected is not None and expected != self.state["revision"]:
            return 409, {"statusCode": 409, "message": "The transcript changed since you last read it."}
        self.state["revision"] += 1
        return 200, {}

    def start_child(self, operation: str, language: str) -> dict:
        child = {"id": str(uuid.uuid4()), "operation": operation, "language": language,
                 "status": "INPROGRESS", "progress": 10, "errorMessage": None, "polls": 0}
        self.state["children"].append(child)
        return child


class _Handler(BaseHTTPRequestHandler):
    def log_message(self, *args) -> None:  # quiet
        pass

    @property
    def fake(self) -> FakeServer:
        return self.server.fake  # type: ignore[attr-defined]

    def _send(self, status: int, payload, headers: dict | None = None, raw: bytes | None = None) -> None:
        body = raw if raw is not None else json.dumps(payload).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/octet-stream" if raw is not None else "application/json")
        self.send_header("x-request-id", "req-test-1")
        for k, v in (headers or {}).items():
            self.send_header(k, str(v))
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(length) or b"{}") if length else {}

    # --- GET ----------------------------------------------------------------
    def do_GET(self) -> None:  # noqa: C901
        f = self.fake
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        st = f.state
        with f.lock:
            st["calls"].append(("GET", url.path, q))
            if url.path.startswith("/audio/"):
                cid = url.path.rsplit("/", 1)[1].split(".")[0]
                data = st["audio"].get(cid)
                return self._send(200 if data else 404, None, raw=data or b"")
            if url.path == "/media/export.mp4":
                data = _mp4()
                rng = self.headers.get("Range")
                if rng:
                    start = int(rng.split("=")[1].rstrip("-"))
                    return self._send(206, None, raw=data[start:])
                return self._send(200, None, raw=data)
            if url.path == f"{PL}/{JOB}/status":
                if st.get("next_status"):
                    st["status"] = st.pop("next_status")
                return self._send(200, {
                    "processId": JOB, "status": st["status"], "isFinished": st["status"] in ("completed", "failed"),
                    "awaitingHumanValidation": st["awaiting"], "sourceLanguage": st["source"],
                    "targetLanguages": st["targets"], "progress": 100 if st["status"] == "completed" else 40,
                    "errorMessage": st.get("error"), "nextPollAfterSeconds": None,
                    "inputData": {"speakers": st["speakers"], "emotionDetection": True, "multiSpeaker": True},
                    "humanValidationTaskIdentifier": "INSTANT-VOICE-CLONING-ENGINE",
                    "tasks": st.get("tasks", []),
                })
            if url.path == "/api/auth/my-permissions":
                perms = st.get("permissions")
                if perms is None:  # an older server: API keys have no active org
                    return self._send(400, {"statusCode": 400, "message": "No active organization"})
                return self._send(200, {"role": "member", "permissions": perms, "personalView": False})
            if url.path == "/v1/org-preference/entitlements":
                return self._send(200, st.get("entitlements", {
                    "galaxies": {"translate_video": True}, "modules": {"translation_memory": True},
                    "resourceModules": {"translation_memory": "translation_memory"}}))
            if url.path == f"{PL}/{JOB}/editor-output":
                data = {"data": {"OUTPUT": [{"transcripts": copy.deepcopy(st["cards"]), "duration": st["duration"],
                                             "source": {"url": f"{f.base}/media/source.mp4"}}]}}
                if q.get("includeRevision") == "true":
                    data["revision"] = st["revision"]
                return self._send(200, {"data": data})
            if url.path.startswith(f"{PL}/") and url.path.endswith("/editor-output"):
                cid = url.path.split("/")[-2]
                exp = st["exports"].get(cid)
                bundle = {"video": exp} if exp else {}
                return self._send(200, {"data": {"data": {"OUTPUT": [bundle]}}})
            if url.path == f"{PL}/{JOB}/pending-children":
                rows = []
                for c in st["children"]:
                    c["polls"] += 1
                    if c["status"] == "INPROGRESS" and c["polls"] >= 2:
                        c["status"] = st["child_outcome"] if c["operation"] != "EXPORT" or not st["export_should_fail"] else "FAILED"
                        if c["status"] == "FAILED":
                            c["errorMessage"] = "worker crashed"
                        elif st["on_child_done"]:
                            st["on_child_done"](st, c)
                        if c["operation"] == "EXPORT" and c["status"] == "DONE":
                            st["exports"][c["id"]] = f"{f.base}/media/export.mp4"
                    rows.append({k: v for k, v in c.items() if k != "polls"})
                return self._send(200, {"data": rows})
            if url.path == f"{PL}/transcript/issues":
                return self._send(200, {"data": st["issues"].get(q.get("lang"), {"errors": [], "warnings": []})})
            if url.path == PL:
                if "uploadId" in q and st["upload_filter"]:
                    rows = [p for p in st["processes"] if p.get("upload") == q["uploadId"]]
                else:
                    rows = list(st["processes"])
                return self._send(200, {"data": rows, "meta": {}})
            if url.path == "/v1/galaxy/translate-video/upload":
                rows = st["uploads"]
                if "checksum" in q:
                    rows = [u for u in rows if u["sha256"] == q["checksum"]]
                return self._send(200, {"data": rows})
            if url.path == "/v1/galaxy/translate-video/voice/cloned":
                return self._send(200, {"data": st["clones"]})
            if url.path == "/v1/credits/balance":
                return self._send(200, {"balance": st["credits"]})
        return self._send(404, {"message": f"no route {url.path}"})

    # --- POST / PUT ---------------------------------------------------------
    def do_PUT(self) -> None:
        self.do_POST(method="PUT")

    def do_POST(self, method: str = "POST") -> None:  # noqa: C901
        f = self.fake
        st = f.state
        path = urlparse(self.path).path
        body = self._body()
        with f.lock:
            st["calls"].append((method, path, body, dict(self.headers)))
            if path in (f"{PL}/transcript/action", f"{PL}/subtitle/action"):
                return self._action(path, body)
            if path == f"{PL}/sync-services/action":
                data = body.get("data") or {}
                card = f.card(data.get("transcriptId"))
                lang = data.get("language") or data.get("targetLanguage")
                if body["action"] == "text-to-speech":
                    # Like the server: a clone referenced without its type is
                    # looked up as a catalog voice and not found.
                    speaker = card["english"].get("speakerId")
                    voice = data.get("voice") or st["speakers"].get(speaker, {}).get(lang, {})
                    clone_ids = {c["id"] for c in st["clones"]}
                    if voice.get("voiceId") in clone_ids and voice.get("voiceType") != "instant-clone":
                        return self._send(404, {"message": "No standard voice found"})
                    card[lang]["a"] = {"url": f"{f.base}/audio/{card['id']}.wav", "d": 1.5, "r": 1.0}
                    st["audio"][card["id"]] = b"RIFF0000WAVE" + uuid.uuid4().bytes
                else:
                    card[lang]["tr"]["text"] = "नया अनुवाद"
                st["revision"] += 1
                return self._send(200, card)
            if path == f"{PL}/{JOB}/generate-all":
                child = f.start_child("GENERATE_ALL", body["targetLanguage"])
                ids = body.get("transcriptIds") or []

                def regen(state, _c, ids=ids, lang=body["targetLanguage"]):
                    for cid in ids:
                        c = next(x for x in state["cards"] if x["id"] == cid)
                        c[lang]["a"] = {"url": f"{f.base}/audio/{cid}.wav", "d": 1.9, "r": 1.05}
                        state["audio"][cid] = b"RIFF0000WAVE" + uuid.uuid4().bytes
                    state["revision"] += 1
                if st["on_child_done"] is None:
                    st["on_child_done"] = regen
                return self._send(201, {"id": child["id"], "processType": "GENERATE_ALL"})
            if path == f"{PL}/{JOB}/autofix-all":
                child = f.start_child("AUTOFIX", body["targetLanguage"])
                return self._send(201, {"id": child["id"], "processType": "TRANSCRIPT_AUTOFIX"})
            if path == f"{PL}/{JOB}/add-language":
                lang = body["targetLanguage"]
                if body.get("expectedSourceRevision") not in (None, st["revision"]):
                    return self._send(409, {"message": "The transcript changed since revision."})
                st["targets"].append(lang)
                child = f.start_child("ADD_LANGUAGE", lang)
                st["last_add_body"] = body
                return self._send(201, {"id": child["id"], "processType": "X", "targetLanguage": st["targets"],
                                        "operation": "ADD_LANGUAGE"})
            if path == f"{PL}/{JOB}/rollback-add-language":
                st["targets"] = [t for t in st["targets"] if t != body["targetLanguage"]]
                st["rolled_back"] = body["targetLanguage"]
                return self._send(200, {})
            if path == f"{PL}/{JOB}/human-validation":
                st["awaiting"] = False
                st["next_status"] = "completed"
                return self._send(200, {"ok": True})
            if path == f"{PL}/{JOB}/retry":
                if st["retry_status"] != 200:
                    return self._send(st["retry_status"], {"message": "Only a failed process can be retried"})
                st["status"] = "running"
                st["awaiting"] = False
                st["next_status"] = "completed"
                return self._send(200, {"processId": JOB, "status": "running"})
            if path == f"{PL}/{JOB}/speaker-voice":
                cleared = []
                for c in st["cards"]:
                    if c["english"].get("speakerId") == body["speakerId"] and body["targetLanguage"] in c:
                        c[body["targetLanguage"]]["a"] = None
                        cleared.append(copy.deepcopy(c))
                st["revision"] += 1
                return self._send(200, {"speakers": st["speakers"], "updatedTranscripts": cleared})
            if path == f"{PL}/{JOB}/assign-speaker":
                f.card(body["transcriptId"])["english"]["speakerId"] = body["speakerId"]
                st["revision"] += 1
                return self._send(200, {"speakerId": body["speakerId"]})
            if path == f"{PL}/export-video":
                child = f.start_child("EXPORT", body["videoLanguage"])
                st["last_export_headers"] = dict(self.headers)
                return self._send(201, {"data": {"id": child["id"]}})
            if path == f"{PL}/presigned-export-url":
                return self._send(200, {"data": {"url": body["s3Url"]}})
        return self._send(404, {"message": f"no route {path}"})

    def _action(self, path: str, body: dict) -> None:
        f = self.fake
        st = f.state
        action, data = body["action"], body.get("data")
        status, err = f.write(body.get("expectedRevision"))
        if status != 200:
            return self._send(status, err)
        if path.endswith("/transcript/action"):
            if action == "update":
                for item in data:
                    card = f.card(item["id"])
                    for key, val in item.items():
                        if isinstance(val, dict):
                            before = (card.get(key) or {}).get("tr", {}).get("text")
                            card[key] = {**card.get(key, {}), **val}
                            # Like the server: new text on a DUBBED line
                            # removes its audio.
                            if (key != st["source"] and st.get("clear_audio_on_text", True)
                                    and "tr" in val and val["tr"].get("text") != before):
                                card[key]["a"] = None
            elif action in ("updateEmotion", "updateRate", "updateKeepSource", "updateLipSync", "updateReviewStatus"):
                field = {"updateEmotion": ("emotion", "emotion"), "updateKeepSource": ("keepSourceAudio", "enabled"),
                         "updateLipSync": ("isLipSync", "enabled"), "updateReviewStatus": ("rs", "status")}.get(action)
                for cid in data["transcriptIds"]:
                    blk = f.card(cid)[data["language"]]
                    if action == "updateRate":
                        # Out-of-range implied video speed: the server picks
                        # its own in-range rate instead of the one asked for.
                        blk["a"]["r"] = data["rate"] if data["rate"] <= 1.05 else 0.9041
                    else:
                        blk[field[0]] = data[field[1]]
            elif action == "saveAudio":
                f.card(data["transcriptId"])[data["language"]]["a"]["volume"] = data["volume"]
            elif action == "split":
                i = [c["id"] for c in st["cards"]].index(data["transcriptId"])
                new = [{"id": data["transcriptId"] if n == 1 else f"n{n}"} for n in range(len(data["chunks"]))]
                st["cards"][i:i + 1] = new
                st["last_action"] = body
                return self._send(200, {"success": True, "chunks": new},
                                  {"X-Transcript-Revision": st["revision"]} if "expectedRevision" in body else None)
            elif action == "add":
                st["cards"].insert(data["index"], data["transcript"])
            elif action == "delete":
                st["cards"] = [c for c in st["cards"] if c["id"] != data["transcriptId"]]
            st["last_action"] = body
        else:
            st["last_subtitle_action"] = body
        headers = {"X-Transcript-Revision": st["revision"]} if "expectedRevision" in body else None
        return self._send(200, {"success": True}, headers)
