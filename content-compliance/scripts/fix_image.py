#!/usr/bin/env python3
"""Make a version of a flagged image that meets a market's rules.

  POST /v1/galaxy/quality-control/classification/decisions/{check}/fix  { regionId, … }
  GET  .../classification/fix-jobs/{id}   until done → the fixed image → --out

`--check` is the `check` value check_content.py printed.

Prints JSON: { "status": "fixed", "path", "changes": "<what was edited>",
               "resolved": [concern titles] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import base64
import json
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import list_markets  # noqa: E402

QC = "/v1/galaxy/quality-control/classification"
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Fix a flagged image for a market.")
    parser.add_argument("--check", required=True, help="From check_content.py.")
    parser.add_argument("--market", required=True, help="Whose concerns to fix.")
    parser.add_argument("--concern", action="append", help="Only these concern titles (default: all).")
    parser.add_argument("--instructions", help="Extra guidance, e.g. 'keep the logo unchanged'.")
    parser.add_argument("--out", default="fixed.png")
    parser.add_argument("--max-wait", type=int, default=900)
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    region = next((r for r in list_markets.regions(base, headers)
                   if (r.get("name") or "").casefold() == args.market.casefold()), None)
    if not region:
        die(_common.EXIT_API_ERROR, f'no market is called "{args.market}".', error_code="MARKET_UNKNOWN")
    body = {"regionId": str(region["id"]), **({"concernTitles": args.concern} if args.concern else {}),
            **({"additionalInstructions": args.instructions} if args.instructions else {})}
    try:
        status, payload = _http.post_json(f"{base}{QC}/decisions/{quote(args.check)}/fix", headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the fix: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "fix images"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    job = (payload.get("jobId") or payload.get("id")) if isinstance(payload, dict) else None
    if status not in (200, 201) or not job:
        die(_common.EXIT_API_ERROR, f"the fix did not start ({status}): {_common.api_message(payload)}")

    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=5)
    while True:
        status, row = _http.get_json(f"{base}{QC}/fix-jobs/{quote(str(job))}", headers=headers)
        state = str((row or {}).get("status") or "").upper() if isinstance(row, dict) else ""
        if state in ("SUCCEEDED", "FAILED"):
            break
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "the fix is still running; run check again later.")
        time.sleep(next(delays))
    result = row.get("result") or {}
    if state == "FAILED" or not result.get("base64"):
        die(_common.EXIT_API_ERROR, f"the fix failed: {row.get('error') or 'no image produced'}", retryable=True)
    out = Path(args.out).expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(base64.b64decode(result["base64"]))
    print(json.dumps({"status": "fixed", "path": str(out), "changes": result.get("editInstructions"),
                      "resolved": [c.get("title") for c in result.get("concerns") or []],
                      "next_action": "check_content"}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
