#!/usr/bin/env python3
"""The media behind ONE card in one language: the source segment it dubs and
its current generated audio — for listening to a line, or handing it to a
reviewer.

  GET .../process-log/{jobId}/editor-output?includeRevision=true

What exists, stated exactly:
  * source      the original video + the card's window (start/end) and text.
                There is no per-card source clip; cut it from the video.
  * raw_audio   the synthesized clip for this line (`a.url`), as generated.
  * playback    NOT a separate file. The player applies `audio_rate`, the
                video rate and the volume while playing / exporting; they are
                reported as `transforms`, never presented as another file.

--download DIR saves the raw clip (and checks it is really audio).

Prints JSON:
  { "card_id", "language", "revision", "text", "voice", "emotion",
    "source": { "video_url", "start", "end", "text" },
    "raw_audio": { "available", "url", "duration_seconds", "sha256", "path"? },
    "playback_audio": { "available": false, "reason", "transforms": {...} } }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cards  # noqa: E402
import _common  # noqa: E402
import _http  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
STATUS_PATH = PL + "/{job_id}/status"

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Source segment and current audio of one card.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--card-id", required=True)
    parser.add_argument("--language", required=True, help="Dubbed language key.")
    parser.add_argument("--download", metavar="DIR", help="Save the raw audio clip here.")
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    try:
        status, row = _http.get_json(base + STATUS_PATH.format(job_id=args.job_id), headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the dub: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this dub"))
    if status != 200:
        die(_common.EXIT_API_ERROR, f"could not read the dub ({status}): {_common.api_message(row)}")
    source_lang = (row or {}).get("sourceLanguage") or ""

    cards, revision = _cards.read_editor(base, headers, args.job_id)
    card = _cards.by_id(cards).get(args.card_id)
    if card is None:
        die(_common.EXIT_API_ERROR, f"card {args.card_id} is not in this dub.")
    blk = _cards.block(card, args.language)
    if not blk:
        die(_common.EXIT_API_ERROR, f"card {args.card_id} has no {args.language} line.")
    src = _cards.block(card, source_lang)
    src_v = src.get("v") if isinstance(src.get("v"), dict) else {}
    v = blk.get("v") if isinstance(blk.get("v"), dict) else {}
    a = blk.get("a") if isinstance(blk.get("a"), dict) else {}
    source_meta = _cards.last_root.get("source")
    video_url = source_meta.get("url") if isinstance(source_meta, dict) else None

    raw = {"available": False, "reason": "this line has no generated audio yet"}
    if a.get("url"):
        raw = {
            "available": True,
            "url": a.get("url"),
            "duration_seconds": a.get("d"),
            "sha256": _cards.audio_hash(a.get("url")),
        }
        if args.download:
            out_dir = Path(args.download).expanduser()
            out_dir.mkdir(parents=True, exist_ok=True)
            dest = out_dir / f"{args.language}-{args.card_id}.wav"
            try:
                _http.download_to_file(a["url"], dest)
            except Exception as e:  # noqa: BLE001
                die(_common.EXIT_DOWNLOAD, f"could not download the audio: {e}")
            head = dest.read_bytes()[:12]
            if not (head[:4] == b"RIFF" and head[8:12] == b"WAVE") and head[:3] != b"ID3" and head[:2] != b"\xff\xfb":
                die(_common.EXIT_DOWNLOAD, "the downloaded file is not audio.")
            raw["path"] = str(dest)

    print(json.dumps({
        "card_id": args.card_id,
        "language": args.language,
        "revision": revision,
        "text": (blk.get("tr") or {}).get("text") if isinstance(blk.get("tr"), dict) else None,
        "voice": a.get("voice") or blk.get("voice"),
        "emotion": blk.get("emotion"),
        "keep_source": bool(blk.get("keepSourceAudio")),
        "source": {
            "video_url": video_url,
            "start": src_v.get("st", v.get("st")),
            "end": src_v.get("et", v.get("et")),
            "text": (src.get("tr") or {}).get("text") if isinstance(src.get("tr"), dict) else None,
        },
        "raw_audio": raw,
        "playback_audio": {
            "available": False,
            "reason": "no separate file: the player applies these while playing and exporting",
            "transforms": {
                "audio_rate": a.get("r"),
                "video_rate": v.get("r"),
                "volume": a.get("volume"),
                "slot": {"start": v.get("st"), "end": v.get("et")},
            },
        },
    }))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
