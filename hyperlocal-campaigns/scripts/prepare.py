#!/usr/bin/env python3
"""Prepare a campaign: resolve the audience and generate each contact's
personalized creative. Spends credits; sends NOTHING (sending is send.py,
after the user says yes).

  POST /v1/galaxy/hyperlocal/broadcast        (never with a schedule)
  GET  /v1/galaxy/hyperlocal/broadcast/{id}   until the creatives are ready

Prints JSON: { "status": "ready_to_send" | "generating", "campaign": "<id>",
               "title", "contacts", "creatives": {"made", "failed"}, "next_action" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _hl  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Prepare a campaign (no sending).")
    parser.add_argument("--title", required=True)
    parser.add_argument("--template", required=True, help="Creative template, by name.")
    parser.add_argument("--channel", action="append", required=True, choices=["whatsapp", "facebook"])
    parser.add_argument("--whatsapp-template", help="Approved WhatsApp message template, by name.")
    parser.add_argument("--facebook-template", help="Facebook template, by name.")
    parser.add_argument("--max-wait", type=int, default=1800)
    _hl.add_audience_args(parser)
    args = parser.parse_args()

    t = _hl.templates()
    body = {"title": args.title,
            "fk_templateId": _hl.by_name(t["creative"], args.template, "creative template", "title", "name"),
            "channels": args.channel, **_hl.audience(args)}
    for channel, name in (("whatsapp", args.whatsapp_template), ("facebook", args.facebook_template)):
        if channel in args.channel:
            if not name:
                _common.die(_common.EXIT_API_ERROR, f"{channel} needs --{channel}-template.",
                            error_code="TEMPLATE_NEEDED", ask=f"Which {channel} message template should it use?")
            body[f"fk_{channel}TemplateId"] = _hl.by_name(t[channel], name, f"{channel} template", "name", "title")

    key = _common.idempotency_key("campaign", body)
    known = _state.recall("hyperlocal-campaigns", key)
    if known:
        bid = known["campaign"]
        sys.stderr.write("[campaign] reconnecting to the campaign already prepared\n")
    else:
        # Deliberately no `schedule`: a scheduled create would send by itself.
        row = _hl.call("POST", "/broadcast", body, what="prepare the campaign")
        row = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else row
        bid = str(row.get("id"))
        _state.remember("hyperlocal-campaigns", key, {"campaign": bid})

    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=5)
    while True:
        b = _hl.broadcast(bid)
        counts = b.get("counts") or {}
        if b.get("status") != "generating" or time.monotonic() >= deadline:
            break
        sys.stderr.write(f"[campaign] creatives {counts.get('generated', 0)}/{counts.get('total', '?')}\n")
        time.sleep(next(delays))
    ready = b.get("status") != "generating"
    print(json.dumps({"status": "ready_to_send" if ready else "generating", "campaign": bid,
                      "title": b.get("title"), "contacts": counts.get("total"),
                      "creatives": {"made": counts.get("generated"), "failed": counts.get("generationFailed")},
                      "next_action": "send" if ready else "prepare"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
