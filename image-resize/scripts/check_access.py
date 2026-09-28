#!/usr/bin/env python3
"""Step 0: can this API key resize images, and which parts?

Run it once before anything else. It asks the server what the key's role
allows and what the organization's plan includes, and prints which steps of
this skill will work — so a missing permission is found now, not halfway
through a job.

Prints JSON:
  { "status": "ready" | "partial" | "blocked" | "unknown",
    "can": [steps], "cannot": [{ step, missing, reason, optional }],
    "next_action": "collect_inputs" | null }

  ready    everything works               → continue
  partial  only optional extras are off   → continue; don't offer those extras
  blocked  a required step is off         → stop; tell the user what to ask
                                            their Vitra admin for
  unknown  the server can't say           → continue; explain any 403 then

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
    {"step": "Upload the image", "needs": ["asset:create"]},
    {"step": "Resize to new sizes", "needs": ["translate_photo.design_agent:create", "translate_photo.design_agent:read"]},
    {"step": "Approve, redo, check and fix sizes", "needs": ["translate_photo.design_agent:create", "translate_photo.design_agent:read"], "optional": True},
    {"step": "Save a size to the Drive", "needs": ["translate_photo.design_agent:create"], "optional": True},
    {"step": "Download (export) the sizes", "needs": ["translate_photo.design_agent:export"], "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
