#!/usr/bin/env python3
"""Translate a subtitle file into one or more languages, files out.

Single source: `sync-lib.sh` copies this file into the subtitle skills. Edit it
here only, then run the sync.

One command: uploads the file (SRT, VTT, ASS or SSA), translates it into every
--target-language keeping each cue's timing, waits, and saves one file per
language in --format (srt by default; vtt, txt and more). Re-running the same
command reconnects to the same job.

Prints JSON:
  { "status": "translated", "job_id", "memory",
    "files": [{"language", "path", "lines"}], "progress", "next_action" }

Stops with a question (`error.ask`) when a choice is the user's:
TARGET_LANGUAGE_NEEDED.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import download_subtitles  # noqa: E402
import start_subtitles  # noqa: E402

die = _common.die


def main() -> int:
    parser = start_subtitles.build_parser()
    parser.description = "Translate a subtitle file into other languages, files out."
    parser.add_argument("--format", default="srt", choices=download_subtitles.FORMATS)
    parser.add_argument("--out-dir", default="translated", help="Where the files go (default ./translated).")
    args = parser.parse_args()
    src = Path(args.file or args.url or "").suffix.lower()
    if src not in start_subtitles.SUBTITLE_EXTENSIONS:
        die(_common.EXIT_API_ERROR, "this translates subtitle files (.srt .vtt .ass .ssa). "
            "For a video, use start_subtitles.py.")
    if args.script:
        die(_common.EXIT_API_ERROR, "--script is for videos.")

    code, started = start_subtitles.run(args)
    if code != _common.EXIT_OK:
        print(json.dumps(started, ensure_ascii=False))
        return code

    out_dir = Path(args.out_dir).expanduser()
    stem = Path(args.file or args.url).stem
    ext = "txt" if args.format.startswith("txt") else args.format
    base, headers = _common.base_url(), _common.headers()
    files = []
    for lang in started.get("target_languages") or []:
        got = download_subtitles.download(base, headers, started["job_id"], lang, args.format,
                                          out_dir / f"{stem}.{lang}.{ext}")
        files.append({"language": lang, "path": got["path"], "lines": got["lines"]})

    print(json.dumps({
        "status": "translated",
        "job_id": started["job_id"],
        "memory": started.get("memory"),
        "files": files,
        "progress": started.get("progress"),
        # Worth offering: review a language, or add more to the same job.
        "next_action": None,
    }, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
