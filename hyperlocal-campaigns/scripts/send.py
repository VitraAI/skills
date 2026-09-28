#!/usr/bin/env python3
"""Send, schedule, pause, resume or stop a prepared campaign. This messages
real people: only after the user saw the reach and cost and said yes.

  --now --confirm-send                          POST .../broadcast/{id}/trigger
  --at "2026-10-01 10:00" --timezone Asia/Kolkata --confirm-send
                                                PUT  .../broadcast/{id}/schedule
  --unschedule | --pause | --resume | --stop    (stop is final)

Prints JSON: { "status": "sending" | "scheduled" | "unscheduled" | "paused" |
               "resumed" | "stopped", "campaign" }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _hl  # noqa: E402
import _http  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Send or control a campaign.")
    parser.add_argument("--campaign", required=True, help="From prepare.py.")
    act = parser.add_mutually_exclusive_group(required=True)
    act.add_argument("--now", action="store_true")
    act.add_argument("--at", help='Local date and time, "YYYY-MM-DD HH:MM".')
    act.add_argument("--unschedule", action="store_true")
    act.add_argument("--pause", action="store_true")
    act.add_argument("--resume", action="store_true")
    act.add_argument("--stop", action="store_true")
    parser.add_argument("--timezone", help='With --at: IANA name, e.g. "Asia/Kolkata".')
    parser.add_argument("--confirm-send", action="store_true",
                        help="Required to send or schedule: the user explicitly approved it.")
    args = parser.parse_args()
    path = f"/broadcast/{quote(args.campaign)}"
    if (args.now or args.at) and not args.confirm_send:
        _common.die(_common.EXIT_API_ERROR, "sending messages real people: get the user's explicit yes, "
                    "then add --confirm-send.", error_code="CONFIRMATION_NEEDED",
                    ask="This will message the contacts now. Send it?")
    if args.now:
        _hl.call("POST", f"{path}/trigger", {}, what="send the campaign")
        status = "sending"
    elif args.at:
        m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})[ T](\d{2}:\d{2})", args.at.strip())
        if not m or not args.timezone:
            _common.die(_common.EXIT_API_ERROR, '--at takes "YYYY-MM-DD HH:MM" and needs --timezone.')
        _hl.call("PUT", f"{path}/schedule", {"date": m[1], "time": m[2], "timezone": args.timezone},
                 what="schedule the campaign")
        status = "scheduled"
    elif args.unschedule:
        base, headers = _common.base_url(), _common.headers()
        code, payload = _http.request_json("DELETE", f"{base}{_hl.HL}{path}/schedule", headers)
        if code not in (200, 204):
            _common.die(_common.EXIT_API_ERROR, f"could not unschedule ({code}): {_common.api_message(payload)}")
        status = "unscheduled"
    else:
        action = "pause" if args.pause else "resume" if args.resume else "stop"
        _hl.call("POST", f"{path}/{action}", {}, what=f"{action} the campaign")
        status = {"pause": "paused", "resume": "resumed", "stop": "stopped"}[action]
    print(json.dumps({"status": status, "campaign": args.campaign}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
