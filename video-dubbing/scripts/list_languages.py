#!/usr/bin/env python3
"""List the language keys the translate-video dub API accepts.

Prints `<key>  <label>` per line. Use the key (left column, e.g.
`hindi_india`) for --source-language / --target-language on dub_video.py.

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

LANGUAGES_PATH = "/v1/language"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List the language keys the translate-video dub API accepts."
    )
    parser.parse_args()

    url = _common.base_url() + LANGUAGES_PATH
    try:
        status, payload = _http.get_json(url, headers=_common.headers())
    except _http.NetworkError as e:
        _common.die(_common.EXIT_DOWNLOAD, f"network error: {e}")

    if status in (401, 403):
        _common.die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status != 200:
        _common.die(
            _common.EXIT_API_ERROR,
            f"error fetching languages ({status}): {_common.api_message(payload)}",
        )

    rows = payload if isinstance(payload, list) else payload.get("data", [])
    for row in rows:
        # The dub API's sourceLanguage / targetLanguages take the `name` field
        # (e.g. `hindi_india`), NOT the ISO `code`.
        key = row.get("name") or ""
        label = row.get("label") or row.get("nativeName") or ""
        if key:
            print(f"{key.ljust(32)} {label}")
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
