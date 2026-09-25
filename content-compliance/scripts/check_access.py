#!/usr/bin/env python3
"""Step 0: can this API key check content against market rules, and which parts?

Prints JSON:
  { "status": "ready" | "partial" | "blocked" | "unknown",
    "can": [steps], "cannot": [{ step, missing, reason, optional }],
    "next_action": "collect_inputs" | null }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _access  # noqa: E402
import _common  # noqa: E402

# Each step of this skill and the permissions its API calls require. Keep in
# step with the scripts.
STEPS = [
    {"step": "See the markets", "needs": ["quality_control.region:read"]},
    {"step": "Check text, images, audio and video", "needs": ["quality_control.classification:create"]},
    {"step": "Read the verdicts", "needs": ["quality_control.classification:read"]},
    {"step": "Fix flagged images", "needs": ["quality_control.classification:create"], "optional": True},
]


def main() -> int:
    result = _access.check(_common.base_url(), _common.headers(), STEPS)
    for c in result["cannot"]:
        sys.stderr.write(f"[access] cannot: {c['step']} ({c['reason']})\n")
    result["next_action"] = None if result["status"] == "blocked" else "collect_inputs"
    print(json.dumps(result))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
