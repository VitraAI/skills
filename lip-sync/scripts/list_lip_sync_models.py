#!/usr/bin/env python3
"""Lip-sync models, and whether this organization can use each.

  GET /v1/galaxy/playground/lip-sync/models

Prints JSON: { "models": [{"model", "label", "available"}] }

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


def main() -> int:
    try:
        status, payload = _http.get_json(_common.base_url() + "/v1/galaxy/playground/lip-sync/models",
                                         headers=_common.headers())
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error listing models: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "list lip-sync models"))
    if status != 200:
        _common.die(_common.EXIT_API_ERROR, f"could not list models ({status}): {_common.api_message(payload)}")
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
    print(json.dumps({"models": [{"model": r.get("value"), "label": r.get("label"),
                                  "available": r.get("available") is True}
                                 for r in rows if isinstance(r, dict)]}))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
