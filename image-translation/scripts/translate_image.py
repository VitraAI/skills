#!/usr/bin/env python3
"""Translate the text inside an image (Vitra Image Translator).

Mirrors what the webapp does:
  1. POST  .../image-translator/analyze          (multipart file | sourceUrl)
     -> jobId
  2. poll  GET .../image-translator/result/{jobId}   until status == 'done'
  3. POST  .../image-translator/{jobId}/translate    -> translationVersionId
  4. poll  GET .../image-translator/{jobId}/translations/{versionId}
     until status == 'completed'  -> translatedImageUrl

Prints JSON: { "status": "completed", "image_url": "...", "job_id": "..." }

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _tm  # noqa: E402

IT = "/v1/galaxy/translate-photo/image-translator"
ANALYZE_PATH = IT + "/analyze"
RESULT_PATH = IT + "/result/{job_id}"
TRANSLATE_PATH = IT + "/{job_id}/translate"
VERSION_PATH = IT + "/{job_id}/translations/{version_id}"
TM_PATH = "/v1/translation-memory"

MAX_SOURCE_BYTES = 10 * 1024 * 1024  # the API caps uploads at 10MB
DEFAULT_POLL_INTERVAL = 5
DEFAULT_MAX_WAIT = 600

ANALYZE_DONE = {"done", "completed", "success"}
TRANSLATE_DONE = {"completed", "done", "success"}
FAILED = {"failed", "error", "cancelled"}

die = _common.die



# Magic bytes for the formats these APIs accept. Checked locally so an obvious
# non-image fails in milliseconds with a clear message, instead of after an
# upload and a queued render that costs credits.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
)


def looks_like_image(path: Path) -> bool:
    """True when the file's leading bytes match a supported image format."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return False
    if any(head.startswith(sig) for sig, _ in _IMAGE_SIGNATURES):
        return True
    # WEBP: "RIFF" .... "WEBP";  TIFF: II*\0 / MM\0*
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return head[:4] in (b"II*\x00", b"MM\x00*")


def resolve_source(file_arg: str | None, url_arg: str | None) -> tuple[Path, bool]:
    """Return (local_path, is_temp). A URL is downloaded to a temp file."""
    if file_arg:
        p = Path(file_arg).expanduser()
        if not p.is_file():
            die(_common.EXIT_DOWNLOAD, f"--file not found: {p}")
        if p.stat().st_size > MAX_SOURCE_BYTES:
            die(_common.EXIT_DOWNLOAD, "image exceeds the 10MB limit")
        if not looks_like_image(p):
            die(
                _common.EXIT_DOWNLOAD,
                f"that file is not an image we can read: {p.name}\n"
                "Supported: PNG, JPEG, GIF, BMP, WEBP, TIFF.",
            )
        return p, False

    parsed = urlparse(url_arg or "")
    if parsed.scheme not in ("http", "https"):
        die(_common.EXIT_DOWNLOAD, "--url must be an http(s) URL")
    name = Path(parsed.path).name or "image.png"
    tmp = Path(tempfile.gettempdir()) / f"vitra-it-{os.getpid()}-{name}"
    try:
        n = _http.download_to_file(url_arg, tmp, MAX_SOURCE_BYTES)
    except _http.NetworkError as e:
        die(_common.EXIT_DOWNLOAD, f"could not download --url: {e}")
    except ValueError as e:
        die(_common.EXIT_DOWNLOAD, str(e))
    sys.stderr.write(f"[source] downloaded {n} bytes\n")
    # A URL can serve an HTML error page with a 200 — check the bytes, not the
    # status, before spending an upload and a render on it.
    if not looks_like_image(tmp):
        try:
            tmp.unlink()
        except OSError:
            pass
        die(
            _common.EXIT_DOWNLOAD,
            "that URL did not return an image (it may be a web page or an "
            "error page). Check the link points directly at an image file.",
        )
    return tmp, True


def unwrap(payload: object) -> dict:
    """Return the object carrying `status`.

    Two shapes are in play, and telling them apart matters:
      * `{ success, data: { status, ... } }`  — envelope, descend into `data`.
      * `{ statusCode, status, data: {...} }` — FLAT, and `data` holds the
        analysis payload, not the job. Descending here loses `status` and the
        caller polls forever.

    So: only descend when the top level does NOT already carry `status`.
    """
    body = payload if isinstance(payload, dict) else {}
    if "status" in body:
        return body
    inner = body.get("data")
    return inner if isinstance(inner, dict) else body


def find_or_create_tm(
    base: str,
    headers: dict,
    source_language: str,
    target_language: str,
    provider: str = "vitratm",
) -> str | None:
    """Reuse the TM for this language pair, or make one.

    Named deterministically from the pair, so every later image translation of
    the same pair lands in the SAME memory — which is the whole point: wording
    approved once gets reused instead of re-translated fresh each run.

    Returns None rather than dying on failure: a missing TM degrades the result
    slightly, but it should never sink an otherwise-fine translation.
    """
    name = f"image · {source_language} → {target_language}"

    try:
        status, payload = _http.get_json(
            f"{base}{TM_PATH}?{urlencode({'search': name})}", headers=headers
        )
        if status == 200:
            rows = payload if isinstance(payload, list) else (payload or {})
            if isinstance(rows, dict):
                rows = rows.get("rows") or rows.get("data") or rows.get("items") or []
            for row in rows:
                if isinstance(row, dict) and row.get("name") == name and row.get("id"):
                    sys.stderr.write(f"[tm] reusing “{name}”\n")
                    return row["id"]
    except _http.NetworkError:
        pass  # fall through to create

    body = {
        "name": name,
        "sourceLanguage": source_language,
        "targetLanguages": [target_language],
        "tmMode": "create",
        "provider": provider,
    }
    try:
        status, payload = _http.post_json(base + TM_PATH, headers, body)
    except _http.NetworkError as e:
        sys.stderr.write(f"[tm] could not create ({e}); continuing without one\n")
        return None

    if status == 409:
        # Raced with another run — the TM now exists; look it up again.
        try:
            _, again = _http.get_json(
                f"{base}{TM_PATH}?{urlencode({'search': name})}", headers=headers
            )
            rows = again if isinstance(again, list) else (again or {})
            if isinstance(rows, dict):
                rows = rows.get("rows") or rows.get("data") or []
            for row in rows:
                if isinstance(row, dict) and row.get("name") == name and row.get("id"):
                    return row["id"]
        except _http.NetworkError:
            pass
        return None

    tm_id = (payload or {}).get("id") if isinstance(payload, dict) else None
    if status not in (200, 201) or not tm_id:
        sys.stderr.write(
            f"[tm] create failed ({status}); continuing without one\n"
        )
        return None
    sys.stderr.write(f"[tm] created “{name}”\n")
    return tm_id


def analyze(
    base: str,
    headers: dict,
    path: Path,
    source_language: str,
    target_language: str,
    tm_id: str | None,
) -> str:
    fields = {
        "sourceLanguage": source_language,
        "targetLanguage": target_language,
    }
    if tm_id:
        fields["tmId"] = tm_id
    try:
        status, payload = _http.post_multipart_json(
            base + ANALYZE_PATH, headers, "file", path, fields=fields
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting analysis: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status not in (200, 201, 202):
        die(
            _common.EXIT_API_ERROR,
            f"analyze failed ({status}): {_common.api_message(payload)}",
        )
    body = payload if isinstance(payload, dict) else {}
    job_id = body.get("jobId") or unwrap(payload).get("jobId")
    if not job_id:
        die(
            _common.EXIT_API_ERROR,
            f"no jobId in analyze response: {_common.api_message(payload)}",
        )
    return job_id


def poll(
    base: str,
    headers: dict,
    url: str,
    done: set[str],
    label: str,
    interval: int,
    max_wait: int,
) -> dict:
    deadline = time.monotonic() + max_wait
    last = None
    while True:
        try:
            code, payload = _http.get_json(base + url, headers=headers)
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error polling {label}: {e}")
        if code != 200:
            die(
                _common.EXIT_API_ERROR,
                f"{label} poll failed ({code}): {_common.api_message(payload)}",
            )
        row = unwrap(payload)
        state = str(row.get("status") or "").lower()
        if state != last:
            sys.stderr.write(f"[{label}] status={state}\n")
            last = state
        if state in done:
            return row
        if state in FAILED:
            die(
                _common.EXIT_API_ERROR,
                f"{label} failed: {row.get('message') or row.get('error') or state}",
            )
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, f"timed out after {max_wait}s waiting for {label}")
        time.sleep(interval)


def start_translation(
    base: str, headers: dict, job_id: str, target_language: str
) -> str:
    try:
        status, payload = _http.post_json(
            base + TRANSLATE_PATH.format(job_id=job_id),
            headers,
            {"targetLanguage": target_language},
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting translation: {e}")
    if status not in (200, 201, 202):
        die(
            _common.EXIT_API_ERROR,
            f"translate failed ({status}): {_common.api_message(payload)}",
        )
    row = unwrap(payload)
    body = payload if isinstance(payload, dict) else {}
    version_id = (
        body.get("translationVersionId")
        or row.get("translationVersionId")
        or row.get("versionId")
        or row.get("id")
    )
    if not version_id:
        die(
            _common.EXIT_API_ERROR,
            f"no translation version id: {_common.api_message(payload)}",
        )
    return version_id


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Translate the text inside an image."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="Local image path (max 10MB).")
    src.add_argument("--url", help="Public http(s) image URL (downloaded, then uploaded).")
    parser.add_argument(
        "--source-language",
        default="auto",
        help="Language in the image, e.g. 'English'. 'auto' (default) auto-detects.",
    )
    parser.add_argument(
        "--target-language",
        required=True,
        help="Language to translate into, e.g. 'French'.",
    )
    tm = parser.add_mutually_exclusive_group()
    tm.add_argument(
        "--tm-name",
        help="Translation Memory to reuse, by the name list_tms.py shows (optional).",
    )
    # Internal handle kept for older callers; people choose by name.
    tm.add_argument("--tm-id", help=argparse.SUPPRESS)
    parser.add_argument(
        "--tm-provider",
        default="vitratm",
        help="Provider for a TM created by --create-tm. Only offer one that "
             "list_providers.py reports as available.",
    )
    parser.add_argument(
        "--create-tm",
        action="store_true",
        help="If no --tm-name is given, find-or-create the TM for this language "
             "pair so terminology stays consistent across runs.",
    )
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    # The caller's choice always wins. --create-tm only fills the gap, and
    # never fails the run: find_or_create_tm returns None if it cannot.
    tm_id = args.tm_id or (
        _tm.resolve_by_name(base, headers, args.tm_name) if args.tm_name else None
    )
    if not tm_id and args.create_tm:
        tm_id = find_or_create_tm(
            base, headers, args.source_language, args.target_language, args.tm_provider
        )

    path, is_temp = resolve_source(args.file, args.url)
    try:
        job_id = analyze(
            base,
            headers,
            path,
            args.source_language,
            args.target_language,
            tm_id,
        )
        sys.stderr.write(f"[analyze] jobId={job_id}\n")

        poll(
            base,
            headers,
            RESULT_PATH.format(job_id=job_id),
            ANALYZE_DONE,
            "analyze",
            args.poll_interval,
            args.max_wait,
        )

        version_id = start_translation(base, headers, job_id, args.target_language)
        sys.stderr.write(f"[translate] versionId={version_id}\n")

        row = poll(
            base,
            headers,
            VERSION_PATH.format(job_id=job_id, version_id=version_id),
            TRANSLATE_DONE,
            "translate",
            args.poll_interval,
            args.max_wait,
        )
    finally:
        if is_temp:
            try:
                path.unlink()
            except OSError:
                pass

    # The version endpoint returns `translatedImageUrl`; some stages of this API
    # use `imageUrl` for the same thing. Accept either.
    url = row.get("translatedImageUrl") or row.get("imageUrl")
    if not url:
        die(
            _common.EXIT_API_ERROR,
            "translation finished but no image url was returned.",
        )

    print(
        json.dumps(
            {
                "status": "completed",
                "image_url": url,
                "job_id": job_id,
                "target_language": row.get("targetLanguage") or args.target_language,
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
