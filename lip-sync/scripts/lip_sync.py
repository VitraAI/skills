#!/usr/bin/env python3
"""Make a video's lips match an audio track (a dub, a new voice-over).

  POST /v1/galaxy/playground/lip-sync      multipart `video` + `audio` + name, language
  GET  /v1/galaxy/playground/lip-sync/{id} until done, then its video link → --out

Re-running the same command reconnects to the render it started.

Prints JSON: { "status": "done" | "failed", "path", "seconds", "next_action" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402

LS = "/v1/galaxy/playground/lip-sync"
DEFAULT_MAX_WAIT = 3600
die = _common.die


def read_job(base: str, headers: dict, job: str) -> dict:
    status, payload = _http.get_json(f"{base}{LS}/{quote(job)}", headers=headers)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read lip-sync jobs"))
    if status != 200 or not isinstance(payload, dict):
        die(_common.EXIT_API_ERROR, f"could not read the lip-sync ({status}): {_common.api_message(payload)}")
    return payload.get("data") if isinstance(payload.get("data"), dict) else payload


def main() -> int:
    parser = argparse.ArgumentParser(description="Lip-sync a video to an audio track.")
    parser.add_argument("--video", required=True, help="The video whose lips should move.")
    parser.add_argument("--audio", required=True, help="The speech they should match.")
    parser.add_argument("--language", required=True, help="Language of the audio, e.g. hindi_india.")
    parser.add_argument("--name", help="Name shown in Vitra. Defaults to the video's name.")
    parser.add_argument("--model", help="A model from list_lip_sync_models.py (default: the organization's).")
    parser.add_argument("--speakers", type=int, help="How many people speak on screen, if more than one.")
    parser.add_argument("--out", help="Where to save the result (default ./<video>.lipsync.mp4).")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    video, audio = Path(args.video).expanduser(), Path(args.audio).expanduser()
    for f in (video, audio):
        if not f.is_file():
            die(_common.EXIT_DOWNLOAD, f"file not found: {f}")
    base, headers = _common.base_url(), _common.headers()
    key = _common.idempotency_key("lipsync", _common.sha256_file(video), _common.sha256_file(audio),
                                  args.language, args.model, args.speakers)
    known = _state.recall("lip-sync", key)
    job = known.get("job") if known else None
    if job:
        sys.stderr.write("[lip-sync] reconnecting to the render already started\n")
    else:
        fields = {"name": args.name or video.stem, "language": args.language,
                  **({"model": args.model} if args.model else {}),
                  **({"numberOfSpeakers": str(args.speakers)} if args.speakers else {})}
        sys.stderr.write("[lip-sync] uploading\n")
        try:
            status, payload = _http.post_multipart_files(
                base + LS, headers, [("video", video), ("audio", audio)], fields, timeout=1800)
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error starting the lip-sync: {e}", retryable=True)
        if status in (401, 403):
            die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "lip-sync videos"))
        if status == 402:
            die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
                error_code="INSUFFICIENT_CREDITS")
        if status not in (200, 201) or not isinstance(payload, dict):
            die(_common.EXIT_API_ERROR, f"the lip-sync did not start ({status}): {_common.api_message(payload)}")
        row = payload.get("data") if isinstance(payload.get("data"), dict) else payload
        job = row.get("id")
        if not job:
            die(_common.EXIT_API_ERROR, "Vitra did not return a lip-sync job.")
        _state.remember("lip-sync", key, {"job": job})

    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=15)
    while True:
        row = read_job(base, headers, job)
        state = str(row.get("status") or "").lower()
        if state in ("done", "failed"):
            break
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "still rendering. Run the same command again to keep waiting; it "
                "will not start a second render.")
        sys.stderr.write("[lip-sync] rendering\n")
        time.sleep(next(delays))
    if state == "failed" or not row.get("outputUrl"):
        _state.forget("lip-sync", key)  # a re-run starts a fresh render
        print(json.dumps({"status": "failed", "error": row.get("error") or "the render failed",
                          "next_action": "lip_sync"}))
        return _common.EXIT_API_ERROR
    out = Path(args.out or f"{video.stem}.lipsync.mp4").expanduser()
    try:
        _http.download_to_file(row["outputUrl"], out, timeout=1800)
    except (_http.NetworkError, ValueError) as e:
        die(_common.EXIT_API_ERROR, f"could not download the video: {e}", retryable=True)
    print(json.dumps({"status": "done", "path": str(out), "seconds": row.get("durationSeconds"),
                      "next_action": None}))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
