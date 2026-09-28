#!/usr/bin/env python3
"""Find the language keys the translate-video API accepts.

  list_languages.py hindi tamil "brazil"

Prints `<key>  <label>` for every language whose key, name or code contains
one of the words (e.g. `hindi_india  Hindi (India)`). Use the key (left) for
the --source-language / --target-language / --language options. There are
over a thousand, so search: with no words it prints only how to.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

LANGUAGES_PATH = "/v1/language"


def main() -> int:
    parser = argparse.ArgumentParser(description="Find the language keys the API accepts.")
    parser.add_argument("words", nargs="*", help='Part of a name, key or code: "hindi", "pt-BR".')
    args = parser.parse_args()
    words = [w.lower() for w in args.words if w.strip()]

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
    if not words:
        print(f"{len(rows)} languages. Search them: list_languages.py <name> [<name> ...]")
        return _common.EXIT_OK
    found = 0
    for row in rows:
        # The API's sourceLanguage / targetLanguages take the `name` field
        # (e.g. `hindi_india`), NOT the ISO `code`.
        key = row.get("name") or ""
        label = row.get("label") or row.get("nativeName") or ""
        hay = f"{key} {label} {row.get('code') or ''}".lower()
        if key and any(w in hay for w in words):
            print(f"{key}  {label}")
            found += 1
    if not found:
        print(f"no language matches {' '.join(args.words)}; try a shorter word, e.g. the language's name.")
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
