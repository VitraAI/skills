#!/usr/bin/env python3
"""The markets (regions) this organization checks content against.

  GET /v1/galaxy/quality-control/region

Prints JSON: { "markets": [{"name", "rules"}] } — pass names to check_content.py.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

REGIONS = "/v1/galaxy/quality-control/region"


def regions(base: str, headers: dict) -> list[dict]:
    try:
        status, payload = _http.get_json(base + REGIONS, headers=headers)
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error listing markets: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read markets"))
    if status != 200:
        _common.die(_common.EXIT_API_ERROR, f"could not list markets ({status}): {_common.api_message(payload)}")
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or (payload or {}).get("regions") or []
    return [r for r in rows if isinstance(r, dict) and r.get("id")]


def main() -> int:
    rows = regions(_common.base_url(), _common.headers())
    print(json.dumps({"markets": [{"name": r.get("name"),
                                   "rules": r.get("ruleCount", r.get("rulesCount"))} for r in rows]},
                     ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
