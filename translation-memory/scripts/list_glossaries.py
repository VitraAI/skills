#!/usr/bin/env python3
"""The organization's glossaries (fixed terms) and style guides (tone and
writing rules) — what translations through its memories follow. With
--style-guide NAME, that guide's rules.

  GET /v1/glossary     GET /v1/style-guide     GET /v1/style-guide/{id}

Prints JSON: { "glossaries": [names], "style_guides": [names] }
          or { "style_guide": {name, …its rules} }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _tm  # noqa: E402

# Bookkeeping a person never needs to read.
HIDDEN = re.compile(r"(^id$|Id$|^fk|At$|^org|^owner|^created|^updated|^deleted)")


def get(base: str, headers: dict, path: str) -> object:
    try:
        status, payload = _http.get_json(base + path, headers=headers)
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read glossaries"))
    if status != 200:
        _common.die(_common.EXIT_API_ERROR, f"could not read ({status}): {_common.api_message(payload)}")
    return payload


def readable(value: object) -> object:
    if isinstance(value, dict):
        return {k: readable(v) for k, v in value.items() if not HIDDEN.search(k) and v not in (None, "", [], {})}
    if isinstance(value, list):
        return [readable(v) for v in value]
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="List glossaries and style guides.")
    parser.add_argument("--style-guide", metavar="NAME", help="Show this style guide's rules.")
    args = parser.parse_args()
    base, headers = _common.base_url(), _common.headers()
    guides = [g for g in _tm.rows_of(get(base, headers, "/v1/style-guide")) if isinstance(g, dict)]
    if args.style_guide:
        hit = next((g for g in guides if (g.get("name") or "").casefold() == args.style_guide.casefold()), None)
        if not hit:
            _common.die(_common.EXIT_API_ERROR, f'no style guide is called "{args.style_guide}". Available: '
                        + (", ".join(g.get("name") or "" for g in guides) or "none"))
        guide = get(base, headers, f"/v1/style-guide/{quote(str(hit.get('id')))}")
        guide = guide.get("data") if isinstance(guide, dict) and isinstance(guide.get("data"), dict) else guide
        print(json.dumps({"style_guide": readable(guide)}, ensure_ascii=False))
        return _common.EXIT_OK
    glossaries = [g for g in _tm.rows_of(get(base, headers, "/v1/glossary")) if isinstance(g, dict)]
    print(json.dumps({"glossaries": [g.get("name") for g in glossaries],
                      "style_guides": [g.get("name") for g in guides]}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
