#!/usr/bin/env python3
"""Step 0: can this API key translate documents, and which parts?

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
    {"step": "Translate documents and text", "needs": ["playground.document:create"]},
    {"step": "Check and download translations", "needs": ["playground.document:read"]},
    {"step": "Choose a translation memory", "needs": ["translation_memory:read"]},
    {"step": "Translate Office files over 25 MB (through the Drive)", "needs": ["asset:create", "asset:read"],
     "optional": True},
    {"step": "Translate a Drive folder", "needs": ["asset:read", "playground.document:create"], "optional": True},
    {"step": "AI proofreading and back-translation", "needs": ["playground.document:create"], "optional": True},
    {"step": "Quality report on a translation", "needs": ["playground.document:read", "aiqe:create", "aiqe:read"],
     "optional": True},
    {"step": "Correct and verify lines, sync with the memory", "needs": ["playground.document:update"],
     "optional": True},
    {"step": "Rename, file and save translations to the Drive", "needs": ["playground.document:update"],
     "optional": True},
    {"step": "Apply a quality report's fixes", "needs": ["playground.document:update", "aiqe:read"],
     "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
