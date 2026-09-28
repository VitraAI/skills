"""One Vitra API call, with the same failure handling in every skill.

Single source: `sync-lib.sh` copies this file into every skill as
`scripts/_api.py`. Edit it here only, then run the sync.

Every script used to carry its own copy of this: build the URL, send JSON,
then turn 401/403 into "your role can't", 402 into "not enough credits", and
anything else into one readable failure line. Keeping it here means a fix to
how an error is explained reaches every skill at once.

Stdlib only.
"""

from __future__ import annotations

import json
from urllib.parse import urlencode

import _common
import _http

die = _common.die


def call(
    method: str,
    path: str,
    body: dict | list | None = None,
    *,
    query: dict | None = None,
    what: str = "",
    timeout: float = 120.0,
    not_found: str | None = None,
    missing_ok: bool = False,
    quiet: bool = False,
) -> object:
    """`method` `path` (from `/v1/…`) with an optional JSON body; the payload.

    `query`: None values are left out. `not_found`: the sentence to say on a
    404 (otherwise the server's own message); `missing_ok`: a 404 returns
    None instead. `quiet`: return None on any failure instead of stopping,
    for optional reads.
    """
    url = _common.base_url() + path
    if query:
        pairs = {k: v for k, v in query.items() if v is not None}
        if pairs:
            url += ("&" if "?" in url else "?") + urlencode(pairs)
    data = json.dumps(body).encode("utf-8") if body is not None else None
    try:
        status, payload = _http.request_json(method, url, _common.headers(), data,
                                             "application/json" if data is not None else None,
                                             timeout=timeout)
    except _http.NetworkError as e:
        if quiet:
            return None
        die(_common.EXIT_API_ERROR, f"network error ({what}): {e}", retryable=True)
    if 200 <= status < 300:
        return payload
    if quiet or (status == 404 and missing_ok):
        return None
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status == 404 and not_found:
        die(_common.EXIT_API_ERROR, not_found)
    die(_common.EXIT_API_ERROR, f"could not {what} ({status}): {_common.api_message(payload)}")
    return None  # unreachable


def data(payload: object) -> dict:
    """The object a route answered with, whether bare or under `data`."""
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def rows(payload: object) -> list[dict]:
    """The list a route answered with: bare, or under data / rows / items."""
    found = payload
    for _ in range(2):
        if isinstance(found, list):
            return [r for r in found if isinstance(r, dict)]
        if not isinstance(found, dict):
            return []
        found = next((found[k] for k in ("data", "rows", "items") if k in found), None)
    return [r for r in found if isinstance(r, dict)] if isinstance(found, list) else []
