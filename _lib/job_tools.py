#!/usr/bin/env python3
"""Everyday controls for a dub or subtitle job, beyond making and editing it.

Single source: `sync-lib.sh` copies this file into the video skills. Edit it
here only, then run the sync.

  cancel         --job-id J                               stop a job that is still running
  cancel-export  --job-id J                               stop an export in progress
  sync           --job-id J (--to-memory | --from-memory) save checked lines to / refresh from the memory
  emotion        --job-id J --language L --emotion calm [--lines 1,4|all]   delivery for voiced lines
  settings       --job-id J [--background-volume 0.3] [--break-subtitles yes|no]
  sheet          --job-id J --type transcript|subtitle [--language L] --out lines.csv
  save           --export-id E                            put a finished export in the Drive
  move           --job-id J --folder NAME|Unassigned      a work folder

Routes under /v1/galaxy/translate-video/process-log: {job}/cancel, cancel-export,
{job}/sync-to-tm, {job}/sync-from-tm, {job}/bulk-emotion, {job}/video-settings,
{job}/excel-data, {export}/save-to-drive, {job}/folder.

Prints JSON. Lines are numbered as in the other scripts; no ids.
Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import csv
import json
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _api  # noqa: E402
import _cards  # noqa: E402
import _common  # noqa: E402
import _folders  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
die = _common.die


def card_ids(job: str, lines: str | None) -> list[str] | None:
    """Line numbers → the job's card ids; None means every line."""
    if not lines or lines.strip().lower() == "all":
        return None
    cards, _ = _cards.read_editor(_common.base_url(), _common.headers(), job)
    try:
        return [_cards.card_at_line(cards, int(n)) for n in lines.split(",") if n.strip()]
    except ValueError:
        die(_common.EXIT_API_ERROR, 'lines are numbers like "1,4", or "all".')
    return None  # unreachable


def main() -> int:
    parser = argparse.ArgumentParser(description="Controls for a dub or subtitle job.")
    parser.add_argument("action", choices=["cancel", "cancel-export", "sync", "emotion", "settings", "sheet",
                                           "save", "move"])
    parser.add_argument("--job-id")
    parser.add_argument("--export-id")
    parser.add_argument("--to-memory", action="store_true")
    parser.add_argument("--from-memory", action="store_true")
    parser.add_argument("--language")
    parser.add_argument("--emotion")
    parser.add_argument("--lines")
    parser.add_argument("--background-volume", type=float, help="0 (silent) to 1 (original).")
    parser.add_argument("--break-subtitles", choices=["yes", "no"])
    parser.add_argument("--type", choices=["transcript", "subtitle"], default="transcript")
    parser.add_argument("--out")
    parser.add_argument("--folder")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if args.action == "save":
        if not args.export_id:
            die(_common.EXIT_API_ERROR, "--export-id is required (from export_dub.py).")
        got = _api.data(_api.call("POST", f"{PL}/{quote(args.export_id)}/save-to-drive", {},
                                  what="save the video to the Drive", timeout=300))
        print(json.dumps({"status": "saved", "file": got.get("name")}, ensure_ascii=False))
        return _common.EXIT_OK
    if not args.job_id:
        die(_common.EXIT_API_ERROR, "--job-id is required.")
    job = quote(args.job_id)

    if args.action == "cancel":
        if not args.confirm:
            die(_common.EXIT_API_ERROR, "cancelling stops the job; work done so far may be lost.",
                error_code="CONFIRM_NEEDED", ask="Stop this job? Then run the same command with --confirm.")
        _api.call("POST", f"{PL}/{job}/cancel", {}, what="cancel the job")
        out: dict = {"status": "cancelled"}
    elif args.action == "cancel-export":
        _api.call("PUT", f"{PL}/cancel-export", {"processId": args.job_id}, what="cancel the export")
        out = {"status": "export_cancelled"}
    elif args.action == "sync":
        if args.to_memory == args.from_memory:
            die(_common.EXIT_API_ERROR, "choose --to-memory or --from-memory.")
        way = "to" if args.to_memory else "from"
        got = _api.data(_api.call("POST", f"{PL}/{job}/sync-{way}-tm", {}, what=f"sync {way} the memory",
                                  timeout=300))
        out = ({"status": "synced_to_memory", "lines": got.get("total")} if args.to_memory else
               {"status": "synced_from_memory", "updated": got.get("pulled"), "skipped": got.get("skipped")})
    elif args.action == "emotion":
        if not (args.language and args.emotion):
            die(_common.EXIT_API_ERROR, "emotion needs --language and --emotion (e.g. calm, happy, excited).")
        ids = card_ids(args.job_id, args.lines)
        _api.call("POST", f"{PL}/{job}/bulk-emotion", {
            "targetLanguage": args.language, "emotion": args.emotion,
            **({"transcriptIds": ids, "regenerateIds": ids} if ids else {})}, what="set the delivery", timeout=300)
        out = {"status": "emotion_set", "emotion": args.emotion, "lines": args.lines or "all",
               "next_action": "regenerate the audio (regenerate_cards) and export again"}
    elif args.action == "settings":
        change = {**({"backgroundVolume": args.background_volume} if args.background_volume is not None else {}),
                  **({"breakSubtitles": args.break_subtitles == "yes"} if args.break_subtitles else {})}
        method = "PUT" if change else "GET"
        got = _api.data(_api.call(method, f"{PL}/{job}/video-settings", change or None, what="the video settings"))
        s = got.get("data") if isinstance(got.get("data"), dict) else got
        out = {"status": "updated" if change else "ok",
               "settings": {k: s.get(k) for k in ("backgroundVolume", "breakSubtitles", "dimension") if k in s}}
    elif args.action == "sheet":
        if not args.out:
            die(_common.EXIT_API_ERROR, "--out is required, e.g. lines.csv.")
        q = urlencode({"type": args.type, **({"language": args.language} if args.language else {})})
        got = _api.call("GET", f"{PL}/{job}/excel-data?{q}", what="read the lines")
        rows = got if isinstance(got, list) else _api.rows(got) or (got.get("subtitles") if isinstance(got, dict)
                                                                     else []) or []
        rows = [r for r in rows if isinstance(r, dict)]
        cols = list(dict.fromkeys(k for r in rows for k in r))
        path = Path(args.out).expanduser()
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="", encoding="utf-8-sig") as fh:  # the BOM makes Excel read UTF-8
            w = csv.DictWriter(fh, fieldnames=cols)
            w.writeheader()
            w.writerows(rows)
        out = {"status": "saved", "path": str(path), "rows": len(rows)}
    else:  # move
        if not args.folder:
            die(_common.EXIT_API_ERROR, "--folder is required (a folder name, or Unassigned).")
        out = _folders.move(f"{PL}/{job}/folder", args.folder)
    print(json.dumps(out, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
