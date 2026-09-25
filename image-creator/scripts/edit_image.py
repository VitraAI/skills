#!/usr/bin/env python3
"""Edit an image that Image Creator already generated, in plain language.

Synchronous, like generate: the API re-renders and returns the new image.

  POST /v1/galaxy/translate-photo/image-creator/{id}/edit  { instructions }
  -> a NEW creation (its own id) derived from the original

Prints JSON: { "status": "completed", "image_url": "...", "creation_id": "...",
               "edited_from": "..." }

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

EDIT_PATH = "/v1/galaxy/translate-photo/image-creator/{id}/edit"
REQUEST_TIMEOUT = 300.0

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Edit a generated image with a text instruction."
    )
    parser.add_argument(
        "--creation-id",
        required=True,
        help="The creation_id returned by generate_image.py (or a prior edit).",
    )
    parser.add_argument(
        "--instructions",
        required=True,
        help="What to change, e.g. 'make the background darker and remove the text'.",
    )
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    sys.stderr.write("[edit] re-rendering…\n")
    try:
        status, payload = _http.post_json(
            base + EDIT_PATH.format(id=args.creation_id),
            headers,
            {"instructions": args.instructions},
            timeout=REQUEST_TIMEOUT,
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error editing image: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status == 404:
        die(
            _common.EXIT_API_ERROR,
            "that image was not found in this organization — check the id.",
        )
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"edit failed ({status}): {_common.api_message(payload)}",
        )

    body = payload if isinstance(payload, dict) else {}
    row = body.get("data") if isinstance(body.get("data"), dict) else body

    if row.get("status") == "failed":
        die(
            _common.EXIT_API_ERROR,
            "the model could not apply that edit — try rephrasing it.",
        )
    url = row.get("url")
    if not url:
        die(
            _common.EXIT_API_ERROR,
            f"no image url in response: {_common.api_message(payload)}",
        )

    print(
        json.dumps(
            {
                "status": "completed",
                "image_url": url,
                "creation_id": row.get("id"),
                "edited_from": row.get("editedFrom") or args.creation_id,
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
