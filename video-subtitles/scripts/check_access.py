#!/usr/bin/env python3
"""Step 0: can this API key make subtitles, and which parts?

Run it once before anything else. It asks the server what the key's role
allows and what the organization's plan includes, and prints which steps of
this skill will work — so a missing permission is found now, not halfway
through a paid job.

Prints JSON:
  { "status": "ready" | "partial" | "blocked" | "unknown",
    "can": [steps], "cannot": [{ step, missing, reason, optional }],
    "next_action": "collect_inputs" | null }

  ready    everything works               → continue
  partial  only optional extras are off   → continue; don't offer those extras
  blocked  a required step is off         → stop; tell the user what to ask
                                            their Vitra admin for
  unknown  the server can't say           → continue; explain any 403 then

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

PL = "translate_video.process_log"

# Each step of this skill and the permissions its API calls require. Keep in
# step with the scripts.
STEPS = [
    {"step": "Upload the video or subtitle file", "needs": ["translate_video.upload:create"]},
    {"step": "Start the subtitles", "needs": [f"{PL}:create"]},
    {"step": "Choose a translation memory", "needs": ["translation_memory:read"]},
    {"step": "Review the subtitles", "needs": [f"{PL}:read"]},
    {"step": "Edit subtitle lines", "needs": [f"{PL}:create"]},
    {"step": "Add a translated subtitle language", "needs": [f"{PL}:create"]},
    {"step": "Download subtitle files, burn subtitles into the video", "needs": [f"{PL}:export"]},
    {"step": "Reuse an earlier upload of the same file", "needs": ["translate_video.upload:read"], "optional": True},
    {"step": "Create a translation memory", "needs": ["translation_memory:create"], "optional": True},
    {"step": "Retry a failed job", "needs": [f"{PL}:update"], "optional": True},
    {"step": "Show the credit balance", "needs": ["credits:read"], "optional": True},
]


def main() -> int:
    result = _access.check(_common.base_url(), _common.headers(), STEPS)
    blocked = result["status"] == "blocked"
    for c in result["cannot"]:
        sys.stderr.write(f"[access] cannot: {c['step']} ({c['reason']})\n")
    result["next_action"] = None if blocked else "collect_inputs"
    print(json.dumps(result))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
