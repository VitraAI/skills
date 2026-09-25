#!/usr/bin/env python3
"""Re-render an already-translated image at a new aspect ratio.

Follow-up to `translate_image.py`: takes the job it returned and regenerates
the image at a different shape. No re-analysis and no re-translation — the
existing translated text is re-composed into the new frame, as a new version.

  POST .../image-translator/{jobId}/resize  { aspectRatio }
  -> { jobId, versionId, versionNumber, imageUrl, aspectRatio }

Synchronous: the call returns the finished image.

Prints JSON:
  { "status": "completed", "image_url": "...", "aspect_ratio": "9:16",
    "job_id": "...", "version_number": 2 }

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

RESIZE_PATH = "/v1/galaxy/translate-photo/image-translator/{job_id}/resize"

# Re-rendering is a model call; the request blocks until the image exists.
REQUEST_TIMEOUT = 300.0

RATIO_RE = re.compile(r"^\d+:\d+$")

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-render a translated image at a new aspect ratio."
    )
    parser.add_argument(
        "--job-id",
        required=True,
        help="The job_id returned by translate_image.py.",
    )
    parser.add_argument(
        "--aspect-ratio",
        required=True,
        help="Target ratio as W:H, e.g. 9:16 (portrait), 1:1 (square), 16:9.",
    )
    args = parser.parse_args()

    ratio = args.aspect_ratio.strip()
    if not RATIO_RE.match(ratio):
        die(
            _common.EXIT_API_ERROR,
            f"--aspect-ratio must look like W:H, e.g. 9:16 (got '{args.aspect_ratio}')",
        )

    sys.stderr.write(f"[resize] re-rendering at {ratio}…\n")
    try:
        status, payload = _http.post_json(
            _common.base_url() + RESIZE_PATH.format(job_id=args.job_id),
            _common.headers(),
            {"aspectRatio": ratio},
            timeout=REQUEST_TIMEOUT,
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error resizing image: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status == 404:
        die(
            _common.EXIT_API_ERROR,
            "that translation job was not found in this organization — check the id.",
        )
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"resize failed ({status}): {_common.api_message(payload)}",
        )

    body = payload if isinstance(payload, dict) else {}
    row = body.get("data") if isinstance(body.get("data"), dict) else body

    url = row.get("imageUrl") or row.get("translatedImageUrl")
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
                "aspect_ratio": row.get("aspectRatio") or ratio,
                "job_id": row.get("jobId") or args.job_id,
                "version_number": row.get("versionNumber"),
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
