#!/usr/bin/env python3
"""Step 0: can this API key do a dub, and which parts?

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
    {"step": "Upload the video", "needs": ["translate_video.upload:create"]},
    {"step": "Start the dub", "needs": [f"{PL}:create"]},
    {"step": "Choose speaker voices", "needs": [f"{PL}:create"]},
    {"step": "Review lines and issues", "needs": [f"{PL}:read"]},
    {"step": "Edit lines", "needs": [f"{PL}:create"]},
    {"step": "Regenerate speech, fix issues, change voices, retry", "needs": [f"{PL}:update"]},
    {"step": "Add another language", "needs": [f"{PL}:create"]},
    {"step": "Export and download", "needs": [f"{PL}:export"]},
    {"step": "Choose a translation memory", "needs": ["translation_memory:read"]},
    {"step": "Reuse an earlier upload of the same file", "needs": ["translate_video.upload:read"], "optional": True},
    {"step": "Offer saved cloned voices", "needs": ["translate_video.voice:read"], "optional": True},
    {"step": "Re-translate or re-voice a single line", "needs": [f"{PL}:create", "translate_video.sync_api:create"], "optional": True},
    {"step": "Create a translation memory in another provider", "needs": ["translation_memory:create"], "optional": True},
    {"step": "Show the credit balance", "needs": ["credits:read"], "optional": True},
    {"step": "See pronunciation rules", "needs": ["translate_video.pronunciation_dictionary:read"], "optional": True},
    {"step": "Add pronunciation rules", "needs": ["translate_video.pronunciation_dictionary:create"],
     "optional": True},
    {"step": "Remove pronunciation rules", "needs": ["translate_video.pronunciation_dictionary:delete"],
     "optional": True},
    {"step": "Type a language's script from Latin letters", "needs": ["translate_video.transliteration:read"],
     "optional": True},
    {"step": "Stop, file and sync jobs; spreadsheet of lines", "needs": ["translate_video.process_log:update",
                                                                        "translate_video.process_log:read"],
     "optional": True},
    {"step": "Save an export to the Drive", "needs": ["translate_video.process_log:create"], "optional": True},
    {"step": "Dub a video from the Drive", "needs": ["translate_video.upload:create", "asset:read"], "optional": True},
]


def main() -> int:
    return _access.report(_common.base_url(), _common.headers(), STEPS)


if __name__ == "__main__":
    sys.exit(main())
