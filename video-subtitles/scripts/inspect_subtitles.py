#!/usr/bin/env python3
"""Read a subtitle job: where it is, its languages, and (optionally) every line.

  GET .../process-log/{id}/status
  GET .../process-log/{id}/editor-output?includeRevision=true

Prints JSON:
  { "status": "ok", "job_id", "progress", "run_status", "revision",
    "source_language", "languages": {"<lang>": {"lines": 42}},
    "suggestions": [{"do", "why", "run", "spends_credits"}], "next_action",
    "lines"?: [{"line", "start", "end", "text"}], "lines_total"?, "more"? }

`--lines <lang>` adds that language's lines, 100 at a time (`more` gives the
next page): what edit_subtitles needs. `suggestions` are the next steps worth
offering, from the data.

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
import _cue  # noqa: E402
import _progress  # noqa: E402
import _tv  # noqa: E402


def languages_of(cards: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for card in cards:
        for key, block in card.items():
            if isinstance(block, dict) and isinstance(block.get("subs"), list):
                counts[key] = counts.get(key, 0) + sum(
                    1 for x in block["subs"] if isinstance(x, dict) and x.get("id"))
    return counts


def suggest(result: dict, job_id: str) -> list[dict]:
    """The next steps worth offering, most useful first, from the job's data."""
    out: list[dict] = []

    def add(do: str, why: str, run: str, credits: bool) -> None:
        out.append({"do": do, "why": why, "run": run, "spends_credits": credits})

    state = str(result.get("run_status") or "").lower()
    if state in ("failed", "cancelled"):
        add("Resume the job from the step that failed", "a retry keeps the finished steps",
            f"retry_subtitles.py --job-id {job_id}", True)
        return out
    if state != "completed":
        add("Wait, then check again", f"the job is still {state or 'starting'}",
            f"inspect_subtitles.py --job-id {job_id}", False)
        return out
    src = result.get("source_language")
    langs = list(result.get("languages") or {})
    translated = [x for x in langs if x != src]
    if src in langs and not translated:
        add(f"Review the {src} subtitles", "every translation is made from them",
            f"inspect_subtitles.py --job-id {job_id} --lines {src}", False)
    rev = result.get("revision")
    add("Add a translated subtitle language", "translated from the reviewed source",
        f"add_subtitle_language.py --job-id {job_id} --language <key>"
        + (f" --expected-revision {rev}" if rev is not None else ""), True)
    if langs:
        add(f"Download subtitles as a file ({', '.join(langs)})", "ready now",
            f"download_subtitles.py --job-id {job_id} --language <key> --format srt --out ./<name>.srt",
            False)
    if result.get("has_video") and langs:
        add("Render the video with subtitles burned in", "one video per language",
            f"burn_subtitles.py --job-id {job_id} --language <key>", True)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Read a subtitle job.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--lines", metavar="LANGUAGE_KEY", help="Also list this language's lines.")
    parser.add_argument("--offset", type=int, default=0, help="With --lines: first line to show (0-based).")
    parser.add_argument("--limit", type=int, default=100, help="With --lines: how many (default 100).")
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    row = _tv.get_status(base, headers, args.job_id)
    cards, revision = _cards.read_editor(base, headers, args.job_id)

    result = {
        "status": "ok",
        "job_id": args.job_id,
        "progress": _progress.run_progress(row),
        "run_status": row.get("status"),
        "revision": revision,
        "source_language": row.get("sourceLanguage"),
        "has_video": row.get("processType") != "SUBTITLE_TO_TRANSCRIPT_TRANSLATION",
        "languages": {k: {"lines": n} for k, n in languages_of(cards).items()},
    }
    result["suggestions"] = suggest(result, args.job_id)
    result["next_action"] = result["suggestions"][0]["run"].split(".py")[0] if result["suggestions"] else None
    if args.lines:
        got = _cue.page(_cue.subtitle_lines(cards, args.lines), args.offset, args.limit,
                        f"--lines {args.lines}")
        result["lines_total"], result["lines"] = got["total"], got["items"]
        if "more" in got:
            result["more"] = got["more"]
    print(json.dumps(result, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
