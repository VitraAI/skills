#!/usr/bin/env python3
"""Make subtitles from a video: transcribed into timed subtitles in the
language spoken (the webapp's Subtitle Generation).

Single source: `sync-lib.sh` copies this file into the skills that use it.
Edit it here only, then run the sync.

  --script (optional): what is said (.srt .vtt .ass .ssa .txt); transcription
  follows it, and a timed script's cues are kept 1:1.

A video needs a translation memory (translated languages added later use it):
one available → used; several → stops with TM_CHOICE_NEEDED and `choices`;
none → stops with TM_NEEDED; --create-tm makes one from the user's answers.

  POST /v1/galaxy/translate-video/upload                (or reuse an identical upload)
  POST /v1/galaxy/translate-video/process-log/publish   (idempotent)
  GET  .../process-log/{id}/status                      until ready

Prints JSON:
  { "status": "review_ready" | "failed", "job_id", "source_language",
    "memory", "progress", "next_action": "inspect_subtitles" }

A subtitle FILE to translate is the subtitle-translation skill's job.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _subtitles  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Make subtitles from a video.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="The video.")
    src.add_argument("--url", help="Public http(s) URL of the video (downloaded, then uploaded).")
    parser.add_argument("--source-language", required=True, metavar="KEY",
                        help="Language spoken in the video (list_languages.py).")
    parser.add_argument("--script", help="Optional: its script (.srt .vtt .ass .ssa .txt).")
    parser.add_argument("--tm-name", help="Translation memory to use, by the name list_tms.py shows.")
    parser.add_argument("--create-tm", action="store_true",
                        help="Create a memory (needs --target-language and --tm-context).")
    parser.add_argument("--target-language", action="append", default=[], metavar="KEY",
                        help="With --create-tm: the languages the memory will translate into.")
    parser.add_argument("--tm-context", help="With --create-tm: who the memory is for. Ask the user.")
    parser.add_argument("--tm-engine", choices=["gemini", "azure"],
                        help="With --create-tm: gemini (default, follows the style guide) or azure.")
    parser.add_argument("--name", help="Name shown in Vitra. Defaults to the file name.")
    parser.add_argument("--max-wait", type=int, default=_subtitles.DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    suffix = Path(args.file or urlparse(args.url or "").path).suffix.lower()
    if suffix in _subtitles.SUBTITLE_EXTENSIONS:
        _common.die(_common.EXIT_API_ERROR, "that's a subtitle file: translating it is the "
                    "subtitle-translation skill's job. This one makes subtitles from a video.",
                    error_code="WRONG_SKILL")
    code, result = _subtitles.run(args, _subtitles.GENERATE, "skill:video-subtitles")
    result.pop("mode", None)
    result.pop("target_languages", None)
    print(json.dumps(result, ensure_ascii=False))
    return code


if __name__ == "__main__":
    sys.exit(main())
