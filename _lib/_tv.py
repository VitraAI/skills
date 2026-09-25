"""Translate-video plumbing shared by the video skills.

Single source: `sync-lib.sh` copies this file into the video skills. Edit it
here only, then run the sync.

Upload (reusing an identical earlier upload), publish (idempotent: a retried
publish returns the first run), read a run's status, and wait for it while
printing progress in the webapp's own steps. Uploads go through the Vitra API
host, never straight to storage, so sandboxed agents can use them.
"""

from __future__ import annotations

import os
import sys
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

import _common
import _http
import _progress

TV = "/v1/galaxy/translate-video"
PL = TV + "/process-log"
UPLOAD_PATH = TV + "/upload"
PUBLISH_PATH = PL + "/publish"
STATUS_PATH = PL + "/{job_id}/status"
LIST_PATH = PL

die = _common.die


def resolve_source(file_arg: str | None, url_arg: str | None) -> tuple[Path, bool]:
    """(local path, is_temp). A URL is downloaded to a temp file first."""
    if file_arg:
        p = Path(file_arg).expanduser()
        if not p.is_file():
            die(_common.EXIT_DOWNLOAD, f"--file not found: {p}")
        return p, False
    parsed = urlparse(url_arg or "")
    if parsed.scheme not in ("http", "https"):
        die(_common.EXIT_DOWNLOAD, "--url must be an http(s) URL")
    name = Path(parsed.path).name or "source"
    tmp = Path(tempfile.gettempdir()) / f"vitra-{os.getpid()}-{name}"
    try:
        n = _http.download_to_file(url_arg, tmp)
    except _http.NetworkError as e:
        die(_common.EXIT_DOWNLOAD, f"could not download --url: {e}")
    except ValueError as e:
        die(_common.EXIT_DOWNLOAD, str(e))
    sys.stderr.write(f"[source] downloaded {n} bytes\n")
    return tmp, True


def find_existing_upload(base: str, headers: dict, sha256: str) -> str | None:
    """An earlier upload of exactly these bytes (matched by content, never name)."""
    try:
        status, payload = _http.get_json(
            f"{base}{UPLOAD_PATH}?{urlencode({'checksum': sha256, 'limit': 1})}", headers=headers
        )
    except _http.NetworkError:
        return None
    if status != 200 or not isinstance(payload, dict):
        return None
    for row in payload.get("data") or payload.get("uploads") or []:
        # Re-check: an older server ignores ?checksum= and lists everything.
        if isinstance(row, dict) and row.get("id") and row.get("sha256") == sha256:
            return row["id"]
    return None


def upload(base: str, headers: dict, path: Path) -> tuple[str, str]:
    """(upload id, sha256). Reuses an identical earlier upload when there is one."""
    sha = _common.sha256_file(path)
    existing = find_existing_upload(base, headers, sha)
    if existing:
        sys.stderr.write("[upload] reusing the earlier upload of this file\n")
        return existing, sha
    try:
        status, payload = _http.post_multipart_json(base + UPLOAD_PATH, headers, "files", path)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error uploading: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "upload files"))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"upload failed ({status}): {_common.api_message(payload)}")
    rows = (payload or {}).get("uploads") or []
    if not rows or not rows[0].get("id"):
        die(_common.EXIT_API_ERROR, f"no upload id in response: {_common.api_message(payload)}")
    sys.stderr.write("[upload] uploaded\n")
    return rows[0]["id"], sha


def publish(base: str, headers: dict, body: dict, idempotency_key: str) -> str:
    """Start a run; the same key returns the first run instead of a second."""
    try:
        status, payload = _http.post_json(
            base + PUBLISH_PATH, {**headers, "Idempotency-Key": idempotency_key}, body
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the job: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "start this job"))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not start ({status}): {_common.api_message(payload)}")
    job_id = (payload or {}).get("processId") or (payload or {}).get("jobId")
    if not job_id:
        die(_common.EXIT_API_ERROR, f"no job id in the response: {_common.api_message(payload)}")
    return job_id


def get_status(base: str, headers: dict, job_id: str) -> dict:
    try:
        status, payload = _http.get_json(base + STATUS_PATH.format(job_id=job_id), headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the job: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this job"))
    if status == 404:
        die(_common.EXIT_API_ERROR, "that job was not found in this organization.")
    if status != 200:
        die(_common.EXIT_API_ERROR, f"could not read the job ({status}): {_common.api_message(payload)}")
    return payload if isinstance(payload, dict) else {}


def wait(base: str, headers: dict, job_id: str, max_wait: int, first_delay: float = 10.0) -> dict:
    """Poll until the run finishes, fails, or stops for the user; return its status.

    Prints a progress line (the webapp's steps) whenever it changes. Times out
    with exit 5 saying the job is still running — re-running reconnects.
    """
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=first_delay)
    last = None
    while True:
        row = get_status(base, headers, job_id)
        line = _progress.line(_progress.run_progress(row))
        if line != last:
            sys.stderr.write(line + "\n")
            last = line
        state = str(row.get("status") or "").lower()
        if row.get("awaitingHumanValidation") or state in ("completed", "failed", "cancelled"):
            return row
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT,
                f"still running after {max_wait}s. Run the same command again to keep waiting; "
                "it will not start a second job.")
        time.sleep(_http.next_poll(row, delays))


EXPORT_PATH = PL + "/export-video"
EDITOR_OUTPUT_PATH = PL + "/{job_id}/editor-output"
SUBTITLE_ACTION_PATH = PL + "/subtitle/action"

# Required by export-video; {1, 1} is the right value for API clients.
NEUTRAL_SCALING = {"x": 1, "y": 1}


def start_export(base: str, headers: dict, body: dict, idempotency_key: str | None) -> str:
    """POST export-video; returns the export's id. `ignoreTranscriptErrors` is
    always false: the server refuses to render a dub with blocking issues. A
    burned-in export uses the language's subtitle style (the server provides
    the default if it has none)."""
    body = {"scalingFactor": NEUTRAL_SCALING, **body, "ignoreTranscriptErrors": False}
    h = {**headers, "Idempotency-Key": idempotency_key} if idempotency_key else headers
    try:
        status, payload = _http.post_json(base + EXPORT_PATH, h, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the export: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "export"))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"the export did not start ({status}): {_common.api_message(payload)}")
    data = (payload or {}).get("data") or {}
    if not data.get("id"):
        die(_common.EXIT_API_ERROR, f"no export id in the response: {_common.api_message(payload)}")
    return data["id"]


def wait_for_export(base: str, headers: dict, job_id: str, export_id: str, max_wait: int) -> str:
    """Wait for a render; return the stored media URL. A render the server marks
    FAILED is reported at once (retryable), not waited on until the timeout."""
    import _jobs

    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=10)
    last = None
    while True:
        try:
            status, payload = _http.get_json(
                base + EDITOR_OUTPUT_PATH.format(job_id=export_id), headers=headers)
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error reading the export: {e}")
        if status == 200:
            data = ((payload or {}).get("data") or {}).get("data") or {}
            out = data.get("OUTPUT")
            bundle = out[0] if isinstance(out, list) and out and isinstance(out[0], dict) else data
            media = bundle.get("video") or bundle.get("audio")
            if isinstance(media, str) and media:
                return media
        row = next((r for r in _jobs.list_children(base, headers, job_id) if r.get("id") == export_id), {})
        if row.get("status") == _jobs.FAILED:
            die(_common.EXIT_API_ERROR, f"the export failed: {row.get('errorMessage') or 'render failed'}",
                error_code="EXPORT_FAILED", retryable=True, export_id=export_id)
        line = f"[export] rendering, {row.get('progress') or 0}%"
        if line != last:
            sys.stderr.write(line + "\n")
            last = line
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT,
                f"the export is still rendering after {max_wait}s. Run download_export.py with "
                "this export id later; do not export again.", export_id=export_id)
        time.sleep(next(delays))


def subtitle_count(cards: list, language: str) -> int:
    """How many subtitle lines a language has across the cards."""
    total = 0
    for card in cards:
        block = card.get(language) if isinstance(card, dict) else None
        subs = block.get("subs") if isinstance(block, dict) else None
        total += len(subs) if isinstance(subs, list) else 0
    return total


def generate_subtitles(base: str, headers: dict, job_id: str, language: str) -> int:
    """Make timed subtitles from a language's translated lines (replacing any
    it had). Synchronous; charged per minute of video. Returns the line count."""
    try:
        status, payload = _http.post_json(
            base + SUBTITLE_ACTION_PATH, headers,
            {"id": job_id, "action": "generate", "data": {"language": language}}, timeout=600)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error generating {language} subtitles: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "generate subtitles"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits to generate subtitles: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR,
            f"could not generate {language} subtitles ({status}): {_common.api_message(payload)}")
    made = (payload or {}).get("generated") if isinstance(payload, dict) else None
    return made if isinstance(made, int) else 0
