#!/usr/bin/env python3
"""Step 0: can this API key run Hyperlocal campaigns, and which parts?

Prints JSON:
  { "status": "ready" | "partial" | "blocked" | "unknown",
    "can": [steps], "cannot": [{ step, missing, reason, optional }],
    "next_action": "collect_inputs" | null }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _access  # noqa: E402
import _common  # noqa: E402

# Each step of this skill and the permissions its API calls require. Keep in
# step with the scripts.
STEPS = [
    {"step": "See contacts, groups and places", "needs": ["hyperlocal.contact:read", "hyperlocal.contact_group:read"]},
    {"step": "See templates", "needs": ["hyperlocal.template:read"]},
    {"step": "Estimate a campaign", "needs": ["hyperlocal.broadcast:read"]},
    {"step": "Prepare a campaign", "needs": ["hyperlocal.broadcast:create"]},
    {"step": "Send, schedule, pause or stop", "needs": ["hyperlocal.broadcast:update"]},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
