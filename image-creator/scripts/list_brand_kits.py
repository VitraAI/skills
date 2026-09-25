#!/usr/bin/env python3
"""List the organization's brand kits.

Prints each kit by name with its colors, fonts and tone, and a `prompt:` line
ready to append to generate_image.py --prompt so the render follows the kit.
No ids: people pick a kit by its name.

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
from brand_kit import describe  # noqa: E402  (the same prompt fragment brand_kit.py prints)

BRAND_KIT_PATH = "/v1/brand-kit"

die = _common.die


def main() -> int:
    argparse.ArgumentParser(
        description="List the organization's brand kits."
    ).parse_args()

    try:
        status, payload = _http.get_json(
            _common.base_url() + BRAND_KIT_PATH, headers=_common.headers()
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status != 200:
        die(
            _common.EXIT_API_ERROR,
            f"could not list brand kits ({status}): {_common.api_message(payload)}",
        )

    # This endpoint answers `{ count, rows }`; other list routes use `data` or
    # `items`, and some return a bare array. Accept all of them.
    rows = payload
    for _ in range(2):
        if isinstance(rows, list):
            break
        if not isinstance(rows, dict):
            rows = []
            break
        for key in ("rows", "data", "items"):
            if key in rows:
                rows = rows[key]
                break
        else:
            rows = []
            break
    if not rows:
        sys.stderr.write("This organization has no brand kits.\n")
        return _common.EXIT_OK
    for k in rows:
        colors = ", ".join(c for c in (k.get("primaryColors") or []) if c)
        fonts = " / ".join(dict.fromkeys(f for f in (k.get("headingFont"), k.get("bodyFont")) if f))
        print(k.get("name") or "(unnamed kit)")
        for label, value in (("colors", colors), ("fonts", fonts), ("tone", k.get("toneOfVoice"))):
            if value:
                print(f"  {label}: {value}")
        fragment = describe(k)
        if fragment:
            print(f"  prompt: {fragment}")
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
