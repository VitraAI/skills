#!/usr/bin/env python3
"""Back-translate a finished document translation: each translated line is
translated back into the source language, so someone who doesn't read the
target language can check the meaning survived.

  POST .../document/ai-back-translation/publish        (a second call reuses the run)
  GET  .../document/ai-back-translation/status/{translation}

Prints JSON: { "status": "done", "lines": N, "items": [{"line", "source",
               "translation", "back"}], "more"? }

Spends credits once per translation. Required env: VITRA_UNIVERSE_API_KEY.
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Back-translate a translation.")
    parser.add_argument("--translation", required=True)
    parser.add_argument("--offset", type=int, default=0)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()
    _doc.call("POST", "/ai-back-translation/publish", {"fk_playgroundLogId": args.translation},
              what="start the back-translation")
    rows = _doc.wait_rows(f"/ai-back-translation/status/{quote(args.translation)}", "back-translation",
                          args.max_wait)
    items = [{"line": n, "translation": r.get("inputText"), "back": r.get("outputText")}
             for n, r in enumerate(rows, 1)]
    page = items[args.offset:args.offset + max(1, args.limit)]
    out = {"status": "done", "lines": len(items), "items": page}
    if args.offset + args.limit < len(items):
        out["more"] = f"--offset {args.offset + args.limit}"
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
