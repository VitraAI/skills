#!/usr/bin/env python3
"""Translate a subtitle file into one or more languages, files out (the
webapp's Subtitle Translation). A subtitle file only; for a video, see
video-subtitles.

Single source: `sync-lib.sh` copies this file into the skills that use it.
Edit it here only, then run the sync.

One command: uploads the file (SRT, VTT, ASS or SSA), translates it into every
--target-language keeping each cue's timing, waits, and saves one file per
language in --format (srt by default; vtt, txt and more). Without --tm-name
the memory for the language pair is found or created. Re-running the same
command reconnects to the same job.

Prints JSON:
  { "status": "translated", "job_id", "memory",
    "files": [{"language", "path", "lines"}], "next_action" }

Stops with a question (`error.ask`): TARGET_LANGUAGE_NEEDED.

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
import download_subtitles  # noqa: E402

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate a subtitle file, files out.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="The subtitle file (.srt .vtt .ass .ssa).")
    src.add_argument("--url", help="Public http(s) URL of it.")
    parser.add_argument("--source-language", required=True, metavar="KEY",
                        help="The file's language (list_languages.py).")
    parser.add_argument("--target-language", action="append", default=[], metavar="KEY",
                        help="Language to translate into (repeatable).")
    parser.add_argument("--tm-name", help="Translation memory, by the name list_tms.py shows.")
    parser.add_argument("--format", default="srt", choices=download_subtitles.FORMATS)
    parser.add_argument("--out-dir", default="translated", help="Where the files go (default ./translated).")
    parser.add_argument("--name", help="Name shown in Vitra. Defaults to the file name.")
    parser.add_argument("--max-wait", type=int, default=_subtitles.DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    source = Path(args.file or urlparse(args.url or "").path)
    if source.suffix.lower() not in _subtitles.SUBTITLE_EXTENSIONS:
        die(_common.EXIT_API_ERROR, "this translates subtitle files only (.srt .vtt .ass .ssa). "
            "Subtitles for a video are the video-subtitles skill's job.", error_code="WRONG_SKILL")
    if not args.target_language:
        die(_common.EXIT_API_ERROR, "which languages should it be translated into?",
            error_code="TARGET_LANGUAGE_NEEDED",
            ask="Which language(s) should these subtitles be translated into?")

    code, started = _subtitles.run(args, _subtitles.TRANSLATE, "skill:subtitle-translation")
    if code != _common.EXIT_OK:
        print(json.dumps(started, ensure_ascii=False))
        return code

    out_dir = Path(args.out_dir).expanduser()
    ext = "txt" if args.format.startswith("txt") else args.format
    base, headers = _common.base_url(), _common.headers()
    files = []
    for lang in started.get("target_languages") or sorted(set(args.target_language)):
        got = download_subtitles.download(base, headers, started["job_id"], lang, args.format,
                                          out_dir / f"{source.stem}.{lang}.{ext}")
        files.append({"language": lang, "path": got["path"], "lines": got["lines"]})

    print(json.dumps({"status": "translated", "job_id": started["job_id"], "memory": started.get("memory"),
                      "files": files, "next_action": None}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
