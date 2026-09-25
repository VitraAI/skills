#!/usr/bin/env python3
"""Change subtitle lines in ONE language: text, timing, split, merge, delete.

Single source: `sync-lib.sh` copies this file into the video skills. Edit it
here only, then run the sync.

Lines are numbered as the skill lists them (1 = the first line of the video).

  --edits '[{"line": 3, "text": "New line\\nsecond row"},
            {"line": 4, "start": 12.5, "end": 14.0}]'   change text / timing
  --split 3 --at-word 6        split line 3 before its 6th word
  --merge 3,4                  merge consecutive lines into one
  --delete 3                   delete line 3

  POST .../process-log/subtitle/action   updateById | split | merge | delete

Pass the `revision` printed with the lines (if not null): if the
subtitles changed since, nothing is saved. Lines already saying what an edit
asks for are left alone. After a split, merge or delete the lines after it are
renumbered: read them again before the next change.

Prints JSON: { "status": "saved", "language", "changes": [{line, field,
               before, after}], "renumbered": bool, "revision_after" }

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
import _http  # noqa: E402

ACTION_PATH = "/v1/galaxy/translate-video/process-log/subtitle/action"
die = _common.die


def pick(lines: list, n: object) -> tuple[str, dict]:
    if not isinstance(n, int) or not 1 <= n <= len(lines):
        die(_common.EXIT_API_ERROR, f"there is no line {n}; this language has {len(lines)}.")
    return lines[n - 1]


def send(base: str, headers: dict, job: str, action: str, data: dict, revision: int | None) -> int | None:
    body: dict = {"id": job, "action": action, "data": data}
    if revision is not None:
        body["expectedRevision"] = revision
    try:
        status, payload = _http.post_json(base + ACTION_PATH, headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error saving: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "edit subtitles"))
    if status == 409:
        die(_common.EXIT_API_ERROR, "the subtitles changed since they were read; nothing was saved. "
            "Read them again and redo the change.", error_code="REVISION_CONFLICT")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not save ({status}): {_common.api_message(payload)}")
    if revision is None:
        return None
    header = _http.last_headers.get("x-transcript-revision")
    return int(header) if header and header.isdigit() else _cards.read_editor(base, headers, job)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Change subtitle lines in one language.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--revision", type=int, help="Printed with the lines, if not null.")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--edits", help='JSON list: [{"line": N, "text"?, "start"?, "end"?}]')
    what.add_argument("--split", type=int, metavar="LINE")
    what.add_argument("--merge", metavar="LINE,LINE")
    what.add_argument("--delete", type=int, metavar="LINE")
    parser.add_argument("--at-word", type=int, help="With --split: the word that starts the second half.")
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    lang = args.language
    cards, current = _cards.read_editor(base, headers, args.job_id)
    if args.revision is not None and current is not None and args.revision != current:
        die(_common.EXIT_API_ERROR, "the subtitles changed since they were read; read them again.",
            error_code="REVISION_CONFLICT", current_revision=current)
    revision = args.revision if args.revision is not None else current
    lines = _cue.numbered(cards, lang)
    if not lines:
        die(_common.EXIT_API_ERROR, f"{lang} has no subtitle lines on this job.", error_code="NO_SUBTITLES")
    path = {"language": lang}
    changes: list[dict] = []
    structural = False

    if args.edits:
        try:
            edits = json.loads(args.edits)
        except ValueError:
            die(_common.EXIT_API_ERROR, '--edits must be JSON, e.g. [{"line": 3, "text": "..."}]')
        if not isinstance(edits, list) or not edits:
            die(_common.EXIT_API_ERROR, "--edits must be a non-empty JSON list.")
        planned = []
        for e in edits:
            n = e.get("line") if isinstance(e, dict) else None
            card_id, sub = pick(lines, n)
            change: dict = {}
            t = dict(sub.get("t") or {})
            if "text" in e:
                if not str(e["text"]).strip():
                    die(_common.EXIT_API_ERROR, f"line {n} can't be empty; delete it instead.")
                if _cue.to_plain(sub.get("text")) != str(e["text"]).strip():
                    changes.append({"line": n, "field": "text", "before": _cue.to_plain(sub.get("text")),
                                    "after": str(e["text"]).strip()})
                    change["text"] = _cue.to_api(e["text"])
            for field, key in (("start", "st"), ("end", "et")):
                if field in e and t.get(key) != float(e[field]):
                    changes.append({"line": n, "field": field, "before": t.get(key), "after": float(e[field])})
                    t[key] = float(e[field])
                    change["t"] = t
            if "t" in change and not t.get("st", 0) < t.get("et", 0):
                die(_common.EXIT_API_ERROR, f"line {n}: the start must be before the end.")
            if change:
                planned.append({"path": {**path, "transcriptId": card_id, "subtitleId": sub["id"]},
                                "subtitle": change})
        for data in planned:
            revision = send(base, headers, args.job_id, "updateById", data, revision)
    elif args.delete is not None:
        card_id, sub = pick(lines, args.delete)
        changes.append({"line": args.delete, "field": "line", "before": _cue.to_plain(sub.get("text")),
                        "after": None})
        revision = send(base, headers, args.job_id, "delete",
                        {"path": {**path, "transcriptId": card_id, "subtitleId": sub["id"]}}, revision)
        structural = True
    elif args.split is not None:
        card_id, sub = pick(lines, args.split)
        words = _cue.to_plain(sub.get("text")).split()
        if not args.at_word or not 1 < args.at_word <= len(words):
            die(_common.EXIT_API_ERROR, f"--at-word must be between 2 and {len(words)} "
                f"(line {args.split} has {len(words)} words).")
        # The API cuts the line itself; time is shared by word count.
        changes.append({"line": args.split, "field": "split", "before": _cue.to_plain(sub.get("text")),
                        "after": [" ".join(words[:args.at_word - 1]), " ".join(words[args.at_word - 1:])]})
        revision = send(base, headers, args.job_id, "split",
                        {"path": {**path, "transcriptId": card_id, "subtitleId": sub["id"]},
                         "atWord": args.at_word - 1}, revision)
        structural = True
    else:
        try:
            nums = sorted(int(x) for x in args.merge.split(",") if x.strip())
        except ValueError:
            die(_common.EXIT_API_ERROR, "--merge takes line numbers, e.g. 3,4")
        picked = [pick(lines, n) for n in nums]
        if len(nums) < 2 or nums != list(range(nums[0], nums[0] + len(nums))) \
                or len({c for c, _ in picked}) != 1:
            die(_common.EXIT_API_ERROR, "only lines next to each other in the same passage can be merged.")
        before = [_cue.to_plain(s.get("text")) for _, s in picked]
        changes.append({"line": nums[0], "field": "merge", "before": before,
                        "after": " ".join(b.replace("\n", " ") for b in before)})
        revision = send(base, headers, args.job_id, "merge",
                        {"path": {**path, "transcriptId": picked[0][0]},
                         "subtitleIds": [s["id"] for _, s in picked]}, revision)
        structural = True

    print(json.dumps({"status": "saved", "language": lang, "changes": changes,
                      "renumbered": structural, "revision_after": revision}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
