#!/usr/bin/env python3
"""Step 0: can this API key translate subtitles, and which parts?

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

PL = "translate_video.process_log"

# Each step of this skill and the permissions its API calls require. Keep in
# step with the scripts.
STEPS = [
    {"step": "Upload the subtitle file", "needs": ["translate_video.upload:create"]},
    {"step": "Translate the subtitles", "needs": [f"{PL}:create"]},
    {"step": "Download the translated files", "needs": [f"{PL}:read", f"{PL}:export"]},
    {"step": "Review and edit lines, add languages", "needs": [f"{PL}:create"], "optional": True},
    {"step": "Reuse an earlier upload of the same file", "needs": ["translate_video.upload:read"], "optional": True},
    {"step": "Choose a translation memory", "needs": ["translation_memory:read"], "optional": True},
    {"step": "Retry a failed job", "needs": [f"{PL}:update"], "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
