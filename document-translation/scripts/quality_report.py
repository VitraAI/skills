#!/usr/bin/env python3
"""Score a finished document translation line by line (accuracy, fluency,
terminology, style) and, if the user wants, apply the suggested fixes to the
document itself.

  POST .../document/qe-report/publish      { fk_playgroundLogId, scope }
  GET  /v1/aiqe/reports/{id}               until finished
  PUT  .../document/qe-report/apply-fix    { reportId, ordinals }  — with --apply-fixes
  GET  .../document/logs/{translation}/export   the fixed file (--out)

Prints JSON: { "status": "scored", "score", "band", "passed",
               "lines_with_errors", "worst": [{"line", …, "better"}] }
  or, with --apply-fixes: { "status": "fixed", "applied", "unchanged",
               "skipped", "path"? }

Spends credits per source word. Required env: VITRA_UNIVERSE_API_KEY.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _aiqe  # noqa: E402
import _common  # noqa: E402
import _doc  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a document translation; apply fixes.")
    parser.add_argument("--translation", required=True)
    parser.add_argument("--scope", choices=["all", "unverified"], default="all",
                        help="Score every line, or only lines nobody reviewed yet.")
    parser.add_argument("--apply-fixes", metavar='LINES|all',
                        help='Apply the corrections: "all", or lines like "4,9".')
    parser.add_argument("--out", help="With --apply-fixes: save the fixed file here.")
    parser.add_argument("--show", type=int, default=10)
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()

    if args.apply_fixes:
        body: dict = {"fk_playgroundLogId": args.translation}
        if args.apply_fixes.strip().lower() != "all":
            try:
                body["ordinals"] = [int(x) for x in args.apply_fixes.split(",") if x.strip()]
            except ValueError:
                _common.die(_common.EXIT_API_ERROR, 'lines are numbers, e.g. "4,9", or "all".')
        got = _doc.call("PUT", "/qe-report/apply-fix", body, what="apply the fixes")
        got = got.get("data") if isinstance(got, dict) and isinstance(got.get("data"), dict) else got or {}
        out = {"status": "fixed", "applied": got.get("applied"), "unchanged": got.get("unchanged"),
               "skipped": got.get("skipped")}
        if args.out:
            out["path"] = _doc.download(args.translation, args.out)
        print(json.dumps(out))
        return 0

    started = _doc.call("POST", "/qe-report/publish", {"fk_playgroundLogId": args.translation,
                                                        "scope": args.scope}, what="start the report")
    started = started.get("data") if isinstance(started, dict) and isinstance(started.get("data"), dict) \
        else started
    report = (started or {}).get("report") or {}
    if not report.get("id"):
        _common.die(_common.EXIT_API_ERROR, "Vitra did not start the report.")
    base, headers = _common.base_url(), _common.headers()
    report = _aiqe.wait(base, headers, report, args.max_wait)
    count, worst = _aiqe.worst_lines(base, headers, str(report["id"]), args.show)
    print(json.dumps({"status": "scored", **_aiqe.summary(report), "worst": worst,
                      "next_action": "quality_report --apply-fixes" if worst else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
