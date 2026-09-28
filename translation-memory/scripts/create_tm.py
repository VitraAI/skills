#!/usr/bin/env python3
"""Create a translation memory: the organization's approved wording for a set
of languages, reused by every Vitra translation that uses it.

  POST /v1/translation-memory   { name, sourceLanguage, targetLanguages, context, engine }

`--context` (one sentence on who it's for: the client or product, and the
audience) is required: every translation through the memory uses it.

Prints JSON: { "status": "created" | "exists", "memory" }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _tm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a translation memory.")
    parser.add_argument("--name", required=True)
    parser.add_argument("--source-language", required=True, help="e.g. en-US or English.")
    parser.add_argument("--target-language", action="append", required=True)
    parser.add_argument("--context", required=True, help="Who it's for: the client or product, and the audience.")
    parser.add_argument("--engine", choices=["gemini", "azure"],
                        help="gemini (default: follows the style guide) or azure (ignores it).")
    args = parser.parse_args()
    base, headers = _common.base_url(), _common.headers()
    if any((t.get("name") or "").strip().casefold() == args.name.strip().casefold() for t in _tm.list_tms(base, headers)):
        print(json.dumps({"status": "exists", "memory": args.name}))
        return _common.EXIT_OK
    tm_id, reason = _tm.create_tm(base, headers, args.name, args.source_language, args.target_language,
                                  args.context, args.engine)
    if not tm_id:
        _common.die(_common.EXIT_API_ERROR, f"could not create the memory ({reason}).")
    print(json.dumps({"status": "created", "memory": args.name}))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
