#!/usr/bin/env python3
"""Turn text into speech in a chosen voice, one audio file per passage.

Paragraphs (blank-line separated) become separate clips, generated together;
a very long paragraph is split at sentence ends. The clips are kept together
in the organization's Video Playground as one session, named --name.

  PUT  /v1/galaxy/playground/video-process/session/{session}   the passages
  POST /v1/galaxy/playground/tts/generate                        each passage
  GET  /v1/galaxy/playground/video-process/{clip}                until done
  then the clip's audio link → --out-dir

Pronunciation: --say "SQL=sequel" (repeat) makes every clip read that word
the way given; Vitra swaps it in just before the audio is made.

Re-running the same command reconnects to the clips it started: finished
ones are kept, only failed ones are made again.

Prints JSON: { "status": "done" | "partial" | "failed", "voice",
               "files": [{"clip", "path", "seconds"}], "next_action" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
import time
import uuid
from pathlib import Path
from urllib.parse import quote, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _api  # noqa: E402
import _common  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402

PG = "/v1/galaxy/playground"
PROVIDERS = ["elevenlabs", "cartesia", "microsoft"]
MAX_CLIP_CHARS = 5000
DEFAULT_MAX_WAIT = 900
die = _common.die


def passages(text: str) -> list[str]:
    """Paragraphs, each under the per-clip limit (split at sentence ends)."""
    out: list[str] = []
    for para in [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]:
        while len(para) > MAX_CLIP_CHARS:
            cut = max(para.rfind(". ", 0, MAX_CLIP_CHARS), para.rfind("? ", 0, MAX_CLIP_CHARS),
                      para.rfind("! ", 0, MAX_CLIP_CHARS))
            cut = cut + 1 if cut > 0 else MAX_CLIP_CHARS
            out.append(para[:cut].strip())
            para = para[cut:].strip()
        out.append(para)
    return out


def call(method: str, base: str, headers: dict, path: str, body: dict, what: str) -> object:
    return _api.call(method, path, body, what=what)


def clip_state(base: str, headers: dict, clip: str) -> dict:
    status, payload = _http.get_json(f"{base}{PG}/video-process/{quote(clip)}", headers=headers)
    if status != 200 or not isinstance(payload, dict):
        die(_common.EXIT_API_ERROR, f"could not read a clip ({status}): {_common.api_message(payload)}")
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Turn text into speech.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="The text to speak.")
    src.add_argument("--text-file", help="A .txt file to speak.")
    parser.add_argument("--language", required=True, help="Language key, e.g. hindi_india (list_languages.py).")
    parser.add_argument("--voice-id", required=True, help="From list_voices.py.")
    parser.add_argument("--provider", required=True, choices=PROVIDERS, help="The voice's provider (list_voices.py).")
    parser.add_argument("--voice-name", help="The voice's name, shown in Vitra.")
    parser.add_argument("--emotion", help="Delivery, e.g. happy, calm (where the voice supports it).")
    parser.add_argument("--say", action="append", default=[], metavar="WORD=HOW",
                        help='Read WORD as HOW, e.g. "SQL=sequel" or "Nguyen=win" (repeat).')
    parser.add_argument("--name", default="Speech", help="Name of the set of clips in Vitra.")
    parser.add_argument("--out-dir", default="speech", help="Where audio files go (default ./speech).")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    sayings = []
    for rule in args.say:
        word, sep, how = rule.partition("=")
        if not sep or not word.strip() or not how.strip():
            die(_common.EXIT_API_ERROR, f'--say takes WORD=HOW, e.g. "SQL=sequel" (got "{rule}").')
        sayings.append({"match": word.strip(), "alias": how.strip()})
    text = args.text if args.text is not None else Path(args.text_file).expanduser().read_text(encoding="utf-8")
    parts = passages(text)
    if not parts:
        die(_common.EXIT_API_ERROR, "there is no text to speak.")
    base, headers = _common.base_url(), _common.headers()
    key = _common.idempotency_key("tts", text, args.language, args.provider, args.voice_id, args.emotion,
                                  *([json.dumps(sayings, sort_keys=True)] if sayings else []))
    known = _state.recall("text-to-speech", key)

    def generate(card_id: str, text_part: str) -> None:
        call("POST", base, headers, f"{PG}/tts/generate", {
            "text": text_part, "targetLanguage": args.language, "provider": args.provider,
            "voiceId": args.voice_id, "sessionId": session, "sessionName": args.name, "cardId": card_id,
            **({"voiceName": args.voice_name} if args.voice_name else {}),
            **({"emotion": args.emotion} if args.emotion else {}),
        }, "generate speech")

    if known:
        session, clips = known["session"], known["clips"]
        sys.stderr.write("[speech] reconnecting to the clips already started\n")
        # Only clips that failed are made again, in place; the rest are kept.
        for clip, part in zip(clips, parts):
            if str(clip_state(base, headers, clip).get("status")).lower() == "failed":
                generate(clip, part)
    else:
        session = str(uuid.uuid4())
        clips = [str(uuid.uuid4()) for _ in parts]
        voice = {"provider": args.provider, "voiceId": args.voice_id,
                 **({"name": args.voice_name} if args.voice_name else {})}
        cards = [{"id": c, "name": f"{args.name} {i}" if len(parts) > 1 else args.name, "text": t,
                  "language": args.language, "voice": voice, **({"emotion": args.emotion} if args.emotion else {}),
                  **({"pronunciations": sayings} if sayings else {})}
                 for i, (c, t) in enumerate(zip(clips, parts), 1)]
        # The clips must exist before they're generated: audio made for a clip
        # Vitra doesn't know is never kept.
        call("PUT", base, headers, f"{PG}/video-process/session/{session}", {"name": args.name, "cards": cards},
             "save the passages")
        for card in cards:
            generate(card["id"], card["text"])
        _state.remember("text-to-speech", key, {"session": session, "clips": clips})
        sys.stderr.write(f"[speech] generating {len(clips)} clip(s)\n")

    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=3)
    rows: dict[str, dict] = {}
    while True:
        rows = {c: clip_state(base, headers, c) for c in clips}
        pending = [c for c, r in rows.items() if str(r.get("status")).lower() not in ("done", "failed")]
        if not pending:
            break
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, f"{len(pending)} clip(s) are still generating. Run the same command "
                "again to keep waiting; nothing is generated twice.")
        time.sleep(next(delays))

    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "-", args.name).strip("-") or "speech"
    files, failed = [], 0
    for i, clip in enumerate(clips, 1):
        row = rows[clip]
        url = row.get("outputUrl")
        if str(row.get("status")).lower() != "done" or not url:
            failed += 1
            files.append({"clip": i, "status": "failed"})
            continue
        ext = Path(urlparse(url).path).suffix or ".mp3"
        dest = out_dir / (f"{stem}-{i}{ext}" if len(clips) > 1 else f"{stem}{ext}")
        try:
            _http.download_to_file(url, dest)
        except (_http.NetworkError, ValueError) as e:
            die(_common.EXIT_API_ERROR, f"could not download clip {i}: {e}", retryable=True)
        files.append({"clip": i, "path": str(dest), "seconds": row.get("durationSeconds")})
    status = "done" if not failed else ("partial" if failed < len(clips) else "failed")
    print(json.dumps({"status": status, **({"voice": args.voice_name} if args.voice_name else {}), "files": files,
                      "speech": session,  # for save_speech.py; never shown
                      "next_action": None if not failed else "speak"}, ensure_ascii=False))
    return _common.EXIT_OK if not failed else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
