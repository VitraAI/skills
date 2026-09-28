"""DITA map calls shared by this skill's scripts.

A map is translated as one "language run" per target language; each run holds
one row per topic (and SVG) in the zip. The ids stay inside the scripts: people
see the map's name, the languages and the topic paths.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from urllib.parse import quote, unquote, urlencode, urlparse

import _api
import _common
import _http

DITA = "/v1/galaxy/translate-photo/dita-map"
DRIVE_DOWNLOAD = "/v1/assets-management/get-presigned-download-url"
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "", timeout: float = 300) -> dict:
    payload = _api.call(method, DITA + path, None if method == "GET" else body or {}, what=what,
                        timeout=timeout, not_found="that DITA map translation was not found in this organization.")
    return payload if isinstance(payload, dict) else {}


def topics(tree: list) -> list[dict]:
    """Every file in the run's folder tree, flattened: {path, status, error, row}."""
    out: list[dict] = []
    stack = list(tree or [])
    while stack:
        node = stack.pop(0)
        if not isinstance(node, dict):
            continue
        if node.get("type") == "folder":
            stack[:0] = node.get("children") or []
        elif node.get("childLogId"):
            out.append({"path": node.get("path") or node.get("name"), "status": str(node.get("status") or ""),
                        "error": node.get("error"), "row": str(node["childLogId"])})
    return out


def status(run: str) -> dict:
    return call("GET", f"/{quote(run)}/files", what="read the map's progress")


def wait(runs: dict[str, str], max_wait: int) -> dict[str, dict]:
    """Poll every language run until none of its topics is still translating."""
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=10)
    while True:
        states = {lang: status(run) for lang, run in runs.items()}
        busy = []
        for lang, s in states.items():
            sm = s.get("summary") or {}
            total = sm.get("total") or 0
            settled = (sm.get("done") or 0) + (sm.get("failed") or 0)
            if not total or settled < total:
                busy.append(f"{lang} {settled}/{total or '?'}")
        if not busy:
            return states
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "the map is still translating. Run the same command again to keep "
                "waiting; it will not start a second translation.")
        sys.stderr.write("[dita] " + ", ".join(busy) + " topics\n")
        time.sleep(next(delays))


def build_zip(run: str, allow_partial: bool) -> dict:
    """Package the run's translated topics; `{url, failed}` or `{refused}`."""
    got = call("POST", f"/{quote(run)}/generate-translation-zip", {"allowPartial": allow_partial},
               what="build the translated zip", timeout=900)
    data = got.get("data") if isinstance(got.get("data"), dict) else {}
    if got.get("success") is False or not data.get("url"):
        return {"refused": _common.api_message(got, "the zip could not be built")}
    return {"url": data["url"], "failed": data.get("failedFileCount") or 0}


def download(url: str, dest: Path) -> str:
    """Fetch the zip; the org's bucket may be private, then ask the Drive for a signed link."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        _http.download_to_file(url, dest, timeout=900)  # never send the API key to storage
        return str(dest)
    except (_http.NetworkError, ValueError):
        pass
    parts = [unquote(p) for p in urlparse(url).path.split("/") if p]
    if "dita-map" not in parts or parts.index("dita-map") < 1:
        die(_common.EXIT_DOWNLOAD, "the translated zip was built but could not be downloaded; "
            "it is in the organization's Vitra Drive.", retryable=True)
    key = "/".join(parts[parts.index("dita-map") - 1:])
    base, headers = _common.base_url(), _common.headers()
    query = urlencode({"fileName": key, "downloadFileName": dest.name})
    try:
        status, payload = _http.get_json(f"{base}{DRIVE_DOWNLOAD}?{query}", headers=headers)
        signed = payload.get("value") if status == 200 and isinstance(payload, dict) else None
        if not signed:
            raise ValueError(f"no download link ({status})")
        _http.download_to_file(signed, dest, timeout=900)
    except (_http.NetworkError, ValueError) as e:
        die(_common.EXIT_DOWNLOAD, f"the translated zip was built but could not be downloaded ({e}); "
            "it is in the organization's Vitra Drive.", retryable=True)
    return str(dest)
