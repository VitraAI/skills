#!/usr/bin/env python3
"""Step 0: can this API key translate images, and which parts?

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
    {"step": "Translate an image", "needs": ["translate_photo.image_translator:create", "translate_photo.image_translator:read"]},
    {"step": "Add languages to a translated image", "needs": ["translate_photo.image_translator:create",
                                                               "translate_photo.image_translator:read"]},
    {"step": "Resize a translated image", "needs": ["translate_photo.image_translator:create"]},
    {"step": "Correct the text in a translated image", "needs": ["translate_photo.image_translator:create", "translate_photo.image_translator:update"],
     "optional": True},
    {"step": "Save a translated image to the Drive", "needs": ["translate_photo.image_translator:export"], "optional": True},
    {"step": "List, retry and file past images", "needs": ["translate_photo.image_translator:read", "translate_photo.image_translator:update"], "optional": True},
    {"step": "Send a campaign image back to Hyperlocal", "needs": ["translate_photo.image_translator:save_template"], "optional": True},
    {"step": "Choose a translation memory", "needs": ["translation_memory:read"]},
    {"step": "Create a translation memory", "needs": ["translation_memory:create"], "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
