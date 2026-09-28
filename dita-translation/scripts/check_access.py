#!/usr/bin/env python3
"""Step 0: can this API key translate DITA maps, and which parts?

Prints JSON:
  { "status": "ready" | "partial" | "blocked" | "unknown",
    "can": [steps], "cannot": [{ step, missing, reason, optional }],
    "next_action": "collect_inputs" | null }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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
    {"step": "Translate DITA maps", "needs": ["translate_photo.dita_map:create"]},
    {"step": "Follow progress and download the zips", "needs": ["translate_photo.dita_map:read"]},
    {"step": "Choose a translation memory", "needs": ["translation_memory:read"]},
    {"step": "Quality report on a translated map", "needs": ["translate_photo.dita_map:read", "aiqe:create",
                                                          "aiqe:read"], "optional": True},
    {"step": "Apply a quality report's fixes", "needs": ["translate_photo.dita_map:update", "aiqe:read"],
     "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
