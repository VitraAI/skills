#!/usr/bin/env python3
"""Generate an image from a text prompt (Vitra Image Creator).

Synchronous: the API renders and returns the finished image in one call.

  POST /v1/galaxy/translate-photo/image-creator/generate  { prompt }
  -> { id, status: 'done', url, mimeType, size, ... }

Prints JSON: { "status": "completed", "image_url": "...", "creation_id": "..." }

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

GENERATE_PATH = "/v1/galaxy/translate-photo/image-creator/generate"

# Rendering can take a while; the request itself blocks until the image exists.
REQUEST_TIMEOUT = 300.0

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Generate an image from a text prompt."
    )
    parser.add_argument(
        "--prompt",
        required=True,
        help="What to draw, e.g. 'a minimalist sale banner with a red gift box'.",
    )
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    sys.stderr.write("[generate] rendering…\n")
    try:
        status, payload = _http.post_json(
            base + GENERATE_PATH,
            headers,
            {"prompt": args.prompt},
            timeout=REQUEST_TIMEOUT,
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error generating image: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"generate failed ({status}): {_common.api_message(payload)}",
        )

    # The controller may wrap the row in a `{ success, data }` envelope.
    body = payload if isinstance(payload, dict) else {}
    row = body.get("data") if isinstance(body.get("data"), dict) else body

    if row.get("status") == "failed":
        die(
            _common.EXIT_API_ERROR,
            "the model could not render this prompt — try rephrasing it.",
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
                "mime_type": row.get("mimeType"),
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
