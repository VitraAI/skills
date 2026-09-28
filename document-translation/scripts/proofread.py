#!/usr/bin/env python3
"""AI proofreading of a finished document translation: every line gets a
suggested correction with the reasons; the user picks which to apply.

  POST .../document/ai-proofreading/publish           (a second call reuses the run)
  GET  .../document/ai-proofreading/status/{translation}
  PUT  .../document/ai-proofreading/apply             { layers }  — with --apply
  GET  .../document/logs/{translation}/export         the corrected file (--out)

  --translation <id>   from translate_document.py's results
  --apply 3,7 | all    accept those lines' suggestions (after the user chose)

Prints JSON:
  { "status": "suggested", "lines": N, "suggestions": [{"line", "source",
    "translation", "suggestion", "why": [..]}] }
  or, with --apply: { "status": "applied", "applied": [lines], "path"? }

Spends credits once per translation. Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _doc  # noqa: E402


def suggestions(rows: list[dict]) -> list[dict]:
    out = []
    for n, r in enumerate(rows, 1):
        result = r.get("output") if isinstance(r.get("output"), dict) else {}
        better = result.get("updatedText")
        if better and better.strip() != str(r.get("translation") or "").strip():
            out.append({"line": n, "source": r.get("text"), "translation": r.get("translation"),
                        "suggestion": better,
                        "why": [c.get("explanation") for c in result.get("corrections") or []
                                if isinstance(c, dict) and c.get("explanation")]})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="AI proofreading of a translation.")
    parser.add_argument("--translation", required=True)
    parser.add_argument("--apply", help='Lines whose suggestion to accept: "3,7" or "all".')
    parser.add_argument("--out", help="With --apply: save the corrected file here.")
    parser.add_argument("--show", type=int, default=30, help="How many suggestions to list.")
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()
    status_path = f"/ai-proofreading/status/{quote(args.translation)}"

    if args.apply:
        rows = _doc.rows(_doc.call("GET", status_path, what="read the proofreading"))
        lines = _doc.parse_lines(args.apply, [s["line"] for s in suggestions(rows)])
        layers = [rows[n - 1].get("layerIndex") for n in lines]
        _doc.call("PUT", "/ai-proofreading/apply", {"fk_playgroundLogId": args.translation, "layers": layers},
                  what="apply the corrections")
        out = {"status": "applied", "applied": lines}
        if args.out:
            out["path"] = _doc.download(args.translation, args.out)
        print(json.dumps(out))
        return 0

    _doc.call("POST", "/ai-proofreading/publish", {"fk_playgroundLogId": args.translation},
              what="start proofreading")
    rows = _doc.wait_rows(status_path, "proofreading", args.max_wait)
    found = suggestions(rows)
    print(json.dumps({"status": "suggested", "lines": len(rows), "suggested": len(found),
                      "suggestions": found[:max(0, args.show)],
                      "next_action": "proofread --apply" if found else None}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
