"""Document Playground calls shared by this skill's review scripts."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import quote

import _common
import _http

DOC = "/v1/galaxy/playground/document"
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "") -> object:
    base, headers = _common.base_url(), _common.headers()
    try:
        if method == "GET":
            status, payload = _http.get_json(base + DOC + path, headers=headers)
        elif method == "PUT":
            status, payload = _http.put_json(base + DOC + path, headers, body or {})
        else:
            status, payload = _http.post_json(base + DOC + path, headers, body or {}, timeout=300)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error ({what}): {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status == 404:
        die(_common.EXIT_API_ERROR, "that translation was not found in this organization.")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not {what} ({status}): {_common.api_message(payload)}")
    return payload


def rows(payload: object) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    return sorted((r for r in data or [] if isinstance(r, dict)),
                  key=lambda r: r.get("layerIndex") if isinstance(r.get("layerIndex"), int) else 0)


def wait_rows(path: str, what: str, max_wait: int) -> list[dict]:
    """Poll a per-line AI pass until every line settled."""
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=5)
    while True:
        got = rows(call("GET", path, what=what))
        pending = [r for r in got if str(r.get("status") or "").upper() in ("TODO", "INIT", "INPROGRESS")]
        if got and not pending:
            return got
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, f"still working ({len(pending)} line(s) left). Run the same command "
                "again; it continues where it is.")
        sys.stderr.write(f"[{what}] {len(got) - len(pending)}/{len(got) or '?'} lines\n")
        time.sleep(next(delays))


def download(translation: str, out: str) -> str:
    dest = Path(out).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _http.download_to_file(f"{_common.base_url()}{DOC}/logs/{quote(translation)}/export?side=target", dest,
                               headers=_common.headers(), timeout=600)
    except (_http.NetworkError, ValueError) as e:
        die(_common.EXIT_API_ERROR, f"could not download the file: {e}", retryable=True)
    return str(dest)


def parse_lines(value: str, known: list[int]) -> list[int]:
    if value.strip().lower() == "all":
        return known
    try:
        wanted = [int(x) for x in value.split(",") if x.strip()]
    except ValueError:
        die(_common.EXIT_API_ERROR, 'lines are numbers, e.g. "3,7", or "all".')
    missing = [n for n in wanted if n not in known]
    if missing:
        die(_common.EXIT_API_ERROR, f"line(s) {missing} have nothing to apply.")
    return wanted
