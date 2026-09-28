#!/usr/bin/env python3
"""Manage cloned voices by name: retry a failed clone, or delete one.

  retry   --voice "Priya"                 clone again from the same samples
  delete  --voice "Priya" [--confirm]     remove it (asks first)

Routes: GET/DELETE /v1/galaxy/playground/voice-clone[/{id}], POST .../{id}/retry

Prints JSON. Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _api  # noqa: E402
import _common  # noqa: E402

CLONE = "/v1/galaxy/playground/voice-clone"
die = _common.die


def find(name: str) -> dict:
    got = _api.call("GET", CLONE, what="list cloned voices")
    rows = _api.rows(got) or (got.get("voices") if isinstance(got, dict) else []) or []
    exact = [r for r in rows if str(r.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return exact[0]
    die(_common.EXIT_API_ERROR, f'no single cloned voice is called "{name}".', error_code="CHOICE_NEEDED",
        choices=sorted({str(r.get("name")) for r in (exact or rows)})[:20], ask="Which voice?")
    return {}  # unreachable


def main() -> int:
    parser = argparse.ArgumentParser(description="Retry or delete a cloned voice.")
    parser.add_argument("action", choices=["retry", "delete"])
    parser.add_argument("--voice", required=True, help="The cloned voice's name.")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()
    voice = find(args.voice)
    vid = quote(str(voice["id"]))
    if args.action == "retry":
        _api.call("POST", f"{CLONE}/{vid}/retry", {}, what="retry the clone", timeout=300)
        print(json.dumps({"status": "retrying", "voice": voice.get("name"), "next_action": "list_cloned_voices"}))
        return _common.EXIT_OK
    if not args.confirm:
        die(_common.EXIT_API_ERROR, "deleting a cloned voice can't be undone.", error_code="CONFIRM_NEEDED",
            ask=f'Delete the cloned voice "{voice.get("name")}"? Then run the same command with --confirm.')
    _api.call("DELETE", f"{CLONE}/{vid}", what="delete the cloned voice")
    print(json.dumps({"status": "deleted", "voice": voice.get("name")}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
