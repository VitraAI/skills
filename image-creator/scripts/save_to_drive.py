#!/usr/bin/env python3
"""File a generated image into the organization's Drive (Asset Management).

  POST /v1/galaxy/translate-photo/image-creator/{id}/save-to-drive

Prints JSON: { "status": "saved", "asset_id": "...", "creation_id": "..." }

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

SAVE_PATH = "/v1/galaxy/translate-photo/image-creator/{id}/save-to-drive"

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Save a generated image to the Drive.")
    parser.add_argument(
        "--creation-id",
        required=True,
        help="The creation_id from generate_image.py / edit_image.py.",
    )
    args = parser.parse_args()

    base = _common.base_url()
    try:
        status, payload = _http.post_json(
            base + SAVE_PATH.format(id=args.creation_id), _common.headers(), {}
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error saving to Drive: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status == 404:
        die(_common.EXIT_API_ERROR, "that image was not found in this organization.")
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"save-to-drive failed ({status}): {_common.api_message(payload)}",
        )

    body = payload if isinstance(payload, dict) else {}
    row = body.get("data") if isinstance(body.get("data"), dict) else body
    print(
        json.dumps(
            {
                "status": "saved",
                "asset_id": row.get("assetId"),
                "creation_id": args.creation_id,
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
