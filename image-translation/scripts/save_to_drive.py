#!/usr/bin/env python3
"""Save a translated image into the organization's Drive.

  --job-id J [--language French] [--folder "Q3 creatives"] [--name "sale-banner-fr"]

Without --language, the newest image; without --folder, the product's default
Drive folder.

  POST .../image-translator/versions/{version}/save-to-drive  { folderId?, name? }

Prints JSON: { "status": "saved", "file", "folder", "language" }

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
import _images  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a translated image to the Drive.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language")
    parser.add_argument("--folder", help="A Drive folder name (default: the product's folder).")
    parser.add_argument("--name", help="The file's name in the Drive.")
    args = parser.parse_args()
    version = _images.latest(args.job_id, args.language)
    out = _drive.save(f"{_images.IT}/versions/{quote(str(version['id']))}/save-to-drive", args.folder, args.name,
                      what="save the image to the Drive")
    print(json.dumps({**out, "language": version.get("targetLanguage")}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
