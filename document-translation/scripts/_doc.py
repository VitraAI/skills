"""Document Playground calls shared by this skill's review scripts."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import quote

import _api
import _common
import _http

DOC = "/v1/galaxy/playground/document"
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "") -> object:
    return _api.call(method, DOC + path, None if method == "GET" else body or {}, what=what, timeout=300,
                     not_found="that translation was not found in this organization.")


def rows(payload: object) -> list[dict]:
    """A per-line AI pass's rows, in document order."""
    return sorted(_api.rows(payload),
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
