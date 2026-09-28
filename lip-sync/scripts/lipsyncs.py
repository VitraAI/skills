#!/usr/bin/env python3
"""Lip-sync follow-ups: what it will cost, redo a failed one, save to the Drive.

  quote  --seconds 45 [--model sync-3]          credits for a video that long, and your balance
  retry  --job J                                redo a failed render
  save   --job J [--folder "Launch videos"] [--name N]

`job` is what lip_sync.py returned. Routes: POST .../lip-sync/quote,
POST .../lip-sync/{job}/retry, POST .../lip-sync/{job}/save-to-assets.

Prints JSON. Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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
import _drive  # noqa: E402

LS = "/v1/galaxy/playground/lip-sync"
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Lip-sync: quote, retry, save.")
    parser.add_argument("action", choices=["quote", "retry", "save"])
    parser.add_argument("--seconds", type=float, help="quote: the video's length in seconds.")
    parser.add_argument("--model")
    parser.add_argument("--job")
    parser.add_argument("--folder")
    parser.add_argument("--name")
    args = parser.parse_args()
    if args.action == "quote":
        if not args.seconds or args.seconds <= 0:
            die(_common.EXIT_API_ERROR, "--seconds is required (the video's length).")
        got = _api.data(_api.call("POST", f"{LS}/quote", {"durationSeconds": args.seconds,
                                                         **({"model": args.model} if args.model else {})},
                                  what="price the lip-sync"))
        credits, balance = got.get("credits"), got.get("balance")
        print(json.dumps({"status": "quoted", "credits": credits, "balance": balance, "model": got.get("model"),
                          "seconds": got.get("seconds"),
                          **({"enough": balance >= credits} if isinstance(balance, (int, float))
                             and isinstance(credits, (int, float)) else {})}))
        return _common.EXIT_OK
    if not args.job:
        die(_common.EXIT_API_ERROR, "--job is required (from lip_sync.py).")
    if args.action == "retry":
        _api.call("POST", f"{LS}/{quote(args.job)}/retry", {}, what="retry the lip-sync", timeout=300)
        print(json.dumps({"status": "retrying", "next_action": "lip_sync.py (same command) to wait and download"}))
    else:
        print(json.dumps(_drive.save(f"{LS}/{quote(args.job)}/save-to-assets", args.folder, args.name,
                                     what="save the video to the Drive"), ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
