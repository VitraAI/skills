#!/usr/bin/env python3
"""Look up how phrases are translated in a memory, and whether each is
verified or approved.

  GET /v1/translation-memory/{id}/terms?search=&language=&status=&limit=

Prints JSON: { "memory", "entries": [{"source", "language", "text", "status"}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _tm  # noqa: E402

TM = "/v1/translation-memory"


def entries(base: str, headers: dict, tm_id: str, **query) -> list[dict]:
    q = urlencode({k: v for k, v in query.items() if v})
    try:
        status, payload = _http.get_json(f"{base}{TM}/{quote(tm_id)}/terms?{q}", headers=headers)
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error searching the memory: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read memories"))
    if status != 200:
        _common.die(_common.EXIT_API_ERROR, f"could not search ({status}): {_common.api_message(payload)}")
    rows = _tm.rows_of(payload) or ((payload or {}).get("terms") if isinstance(payload, dict) else []) or []
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        out.append({k: v for k, v in {
            "source": r.get("sourceText"), "language": r.get("targetLanguage"),
            "text": r.get("targetText"), "status": r.get("status")}.items() if v is not None})
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Search a translation memory.")
    parser.add_argument("--tm-name", required=True)
    parser.add_argument("--search", help="Part of the source or translated text.")
    parser.add_argument("--language", help="Target language, as the memory lists it.")
    parser.add_argument("--status", choices=["unverified", "verified", "approved"])
    parser.add_argument("--limit", type=int, default=25)
    args = parser.parse_args()
    base, headers = _common.base_url(), _common.headers()
    tm = _tm.resolve(base, headers, args.tm_name)
    found = entries(base, headers, str(tm["id"]), search=args.search, language=args.language,
                    status=args.status, limit=min(max(args.limit, 1), 200))
    print(json.dumps({"memory": tm.get("name"), "entries": found}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
