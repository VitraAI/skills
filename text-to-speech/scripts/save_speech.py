#!/usr/bin/env python3
"""Save a set of generated speech clips into the organization's Drive.

  --speech S [--folder "Voiceovers"] [--name N]

`speech` is what speak.py returned.
  POST /v1/galaxy/playground/tts/sessions/{speech}/save-to-assets  { folderId?, name? }

Prints JSON: { "status": "saved", "file", "folder" }
Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _drive  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Save generated speech to the Drive.")
    parser.add_argument("--speech", required=True, help="From speak.py.")
    parser.add_argument("--folder")
    parser.add_argument("--name")
    args = parser.parse_args()
    print(json.dumps(_drive.save(f"/v1/galaxy/playground/tts/sessions/{quote(args.speech)}/save-to-assets",
                                 args.folder, args.name, what="save the speech to the Drive"), ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
