#!/usr/bin/env python3
"""Step 0: can this API key manage translation memories, and which parts?

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
    {"step": "Find memories, search entries, glossaries and style guides", "needs": ["translation_memory:read"]},
    {"step": "Translate text through a memory", "needs": ["translation_memory:read"]},
    {"step": "Correct entries", "needs": ["translation_memory:update"], "optional": True},
    {"step": "Create a memory", "needs": ["translation_memory:create"], "optional": True},
    {"step": "Import a file of translations", "needs": ["translation_memory:import"], "optional": True},
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
