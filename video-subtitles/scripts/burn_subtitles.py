#!/usr/bin/env python3
"""Render the video with one language's subtitles burned in.

The webapp's export for a subtitle job: the original video, with the chosen
language's subtitles drawn on it in that language's style (the editor's
default if it has none yet).

  POST .../process-log/export-video        { subtitleOnly, embedSubtitle, subtitleLanguage }
  GET  .../process-log/{exportId}/editor-output   until the video is stored

For a dub, burn subtitles into the dubbed video with video-dubbing's
export_dub.py --subtitles instead. Subtitle files (no video) can't be burned
in: use download_subtitles.py.

Prints JSON: { "status": "exported", "language", "export_id", "media_url",
               "next_action": "download_export" }

Charged per render. Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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
import _tv  # noqa: E402

FILE_ONLY = "SUBTITLE_TO_TRANSCRIPT_TRANSLATION"
DEFAULT_MAX_WAIT = 1800
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Burn one language's subtitles into the video.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True, help="Whose subtitles to burn in.")
    parser.add_argument("--resolution", default="1080", choices=["4K", "2K", "1080", "720", "480", "360"])
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    row = _tv.get_status(base, headers, args.job_id)
    if row.get("processType") == FILE_ONLY:
        die(_common.EXIT_API_ERROR, "this job was made from a subtitle file, so there is no video to "
            "burn subtitles into. Download the subtitles instead (download_subtitles.py).")
    if str(row.get("status") or "").lower() != "completed":
        die(_common.EXIT_API_ERROR, "the subtitles aren't ready yet; check inspect_subtitles.py.")
    cards, revision = _cards.read_editor(base, headers, args.job_id)
    if not _tv.subtitle_count(cards, args.language):
        die(_common.EXIT_API_ERROR, f"{args.language} has no subtitles on this job.",
            error_code="NO_SUBTITLES")

    # One video, the undubbed original: its language is the source language and
    # the subtitle language picks what is drawn on it (the webapp's body).
    body = {
        "processId": args.job_id,
        "resolution": args.resolution,
        "videoLanguage": row.get("sourceLanguage"),
        "lipSync": False,
        "subtitleOnly": True,
        "embedSubtitle": True,
        "subtitleLanguage": args.language,
    }
    key = (_common.idempotency_key("burn", args.job_id, args.language, args.resolution, revision)
           if revision is not None else None)
    sys.stderr.write(f"[export] rendering with {args.language} subtitles…\n")
    export_id = _tv.start_export(base, headers, body, key)
    media_url = _tv.wait_for_export(base, headers, args.job_id, export_id, args.max_wait)
    print(json.dumps({"status": "exported", "language": args.language, "export_id": export_id,
                      "media_url": media_url, "next_action": "download_export"}))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
