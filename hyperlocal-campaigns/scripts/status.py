#!/usr/bin/env python3
"""Where a campaign is, and how delivery is going per channel.

Prints JSON: { "title", "status", "scheduled_for", "whatsapp": {"total",
               "sent", "delivered", "read", "failed", "pending"},
               "facebook": {"total", "posted", "failed", "pending"} }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _hl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="A campaign's status and delivery.")
    parser.add_argument("--campaign", required=True)
    args = parser.parse_args()
    b = _hl.broadcast(args.campaign)
    a = _hl.call("GET", f"/broadcast/{quote(args.campaign)}/analytics", what="read delivery", quiet=True) or {}
    a = a.get("data") if isinstance(a, dict) and isinstance(a.get("data"), dict) else (a or {})
    keep = lambda d, *k: {x: d.get(x) for x in k} if isinstance(d, dict) else None  # noqa: E731
    print(json.dumps({"title": b.get("title"), "status": b.get("status"),
                      "scheduled_for": b.get("scheduledAt") or b.get("schedule"),
                      "whatsapp": keep(a.get("whatsapp"), "total", "sent", "delivered", "read", "failed", "pending"),
                      "facebook": keep(a.get("facebook"), "total", "posted", "failed", "pending")},
                     ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
