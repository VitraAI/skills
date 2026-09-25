"""Stdlib-only HTTP helpers shared by every Vitra skill's scripts (single source:
`_lib/_http.py` in the skills repo, copied into each skill by `sync-lib.sh`).

No third-party dependencies. urllib.request + json + mimetypes + secrets.
Each JSON helper returns a (status_code, parsed_payload) tuple so callers can
branch on status without catching exceptions for the common 4xx/5xx cases.
"""

from __future__ import annotations

import json
import os
import mimetypes
import secrets
import socket
import ssl
import random
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


class NetworkError(Exception):
    """Raised when a request never reaches the server (DNS, connection, timeout).

    Carries a message written for a PERSON. Call sites interpolate this into
    user-facing output, and urllib's native text ("<urlopen error [Errno 8]
    nodename nor servname provided, or not known>") is Python internals that
    tell a caller nothing they can act on.
    """


def humanize(exc: Exception) -> str:
    """A plain-language cause for a connection-level failure."""
    import errno as _errno

    reason = getattr(exc, "reason", exc)
    err_no = getattr(reason, "errno", None)

    if isinstance(reason, (socket.timeout, TimeoutError)) or "timed out" in str(reason).lower():
        return "the server took too long to respond"
    if err_no in (_errno.ENOTFOUND if hasattr(_errno, "ENOTFOUND") else -2, -2, -3, 8):
        return "that address could not be found — check the URL or hostname"
    if err_no == _errno.ECONNREFUSED:
        return "the server refused the connection — it may be down"
    if isinstance(reason, ssl.SSLError) or "certificate" in str(reason).lower():
        return "the secure connection failed (certificate problem)"
    if err_no == _errno.ENETUNREACH:
        return "the network is unreachable — check your connection"
    text = str(reason).strip()
    # Strip urllib's angle-bracket wrapper if it survived this far.
    if text.startswith("<") and text.endswith(">"):
        text = text[1:-1]
    return text or "the connection failed"


# A rate-limited API key is refused by the auth layer BEFORE the handler runs,
# so a 429 means nothing happened and the request is safe to repeat — even a
# POST. The key allows 60 requests and refills after a minute without any; the
# server says exactly how long via `Retry-After`.
# Headers of the most recent response, for the few callers that need one
# (request id for error reports, the transcript revision after an edit).
# Module state rather than a new return value, so no call site changes.
last_headers: dict[str, str] = {}


def last_request_id() -> str | None:
    """The server's id for the last request — quote it when reporting a failure."""
    return last_headers.get("x-request-id")


RATE_LIMIT_RETRIES = 3
GATEWAY_RETRY_READS = {502, 503, 504}
RATE_LIMIT_MAX_WAIT = 90  # seconds; never trust an unbounded server hint


def _retry_after_seconds(headers, payload: object) -> float:
    """Seconds to wait before retrying a 429, from the header or the body."""
    for raw in (
        headers.get("Retry-After") if headers is not None else None,
        payload.get("retryAfterSeconds") if isinstance(payload, dict) else None,
    ):
        try:
            if raw is not None:
                return max(1.0, min(float(raw), RATE_LIMIT_MAX_WAIT))
        except (TypeError, ValueError):
            continue
    return 30.0


def poll_delays(first: float = 5.0, cap: float = 30.0):
    """Exponential backoff for status polling: 5, 10, 20, 30, 30, …

    Polling is what spends the rate limit. A fixed 5s interval makes ~180
    calls over a 15-minute job; this makes ~35 with no meaningful delay in
    noticing that a long job finished.
    """
    if os.environ.get("VITRA_DUB_FAST_POLL") == "1":  # the skill's own tests
        while True:
            yield 0.0
    delay = first
    while True:
        yield delay
        delay = min(delay * 2, cap)


def next_poll(status_payload: object, delays) -> float:
    """Seconds to sleep before the next status poll.

    The server's `nextPollAfterSeconds` when it gives one (bounded, so a bad
    hint can neither hammer the API nor stall the run), else our own backoff.
    Always advances the backoff so a later fallback does not restart at 5s.
    """
    fallback = next(delays)
    hint = status_payload.get("nextPollAfterSeconds") if isinstance(status_payload, dict) else None
    if isinstance(hint, (int, float)) and hint > 0 and fallback > 0:
        return max(5.0, min(float(hint), 60.0))
    return fallback


def request_json(
    method: str,
    url: str,
    headers: dict[str, str],
    body: bytes | None = None,
    content_type: str | None = None,
    timeout: float = 60.0,
) -> tuple[int, object]:
    """Issue an HTTP request and parse the response as JSON.

    Returns (status_code, payload). When the body isn't valid JSON the payload
    is `{"_raw": <text>}` so callers can still surface useful diagnostics.
    Raises NetworkError on connection-level failures only.

    A 429 (rate limited) is waited out and retried here, so callers never see
    one unless the limit stays exhausted across every retry.
    """
    req_headers = dict(headers)
    if content_type is not None:
        req_headers["Content-Type"] = content_type

    for attempt in range(RATE_LIMIT_RETRIES + 1):
        req = urllib.request.Request(url, data=body, headers=req_headers, method=method)
        resp_headers = None
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
                status = resp.status
                resp_headers = resp.headers
        except urllib.error.HTTPError as e:
            raw = e.read() if e.fp is not None else b""
            status = e.code
            resp_headers = e.headers
        except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
            raise NetworkError(humanize(e)) from e

        last_headers.clear()
        if resp_headers is not None:
            last_headers.update({k.lower(): v for k, v in resp_headers.items()})

        text = raw.decode("utf-8", errors="replace")
        try:
            payload: object = json.loads(text) if text else None
        except json.JSONDecodeError:
            payload = {"_raw": text}

        # A gateway error means the request did not get a real answer. Safe to
        # repeat for reads; for writes only 503 ("no available server": it
        # never reached the app) — a 502/504 write may already have applied.
        gateway = status in GATEWAY_RETRY_READS if method == "GET" else status == 503
        if (status != 429 and not gateway) or attempt == RATE_LIMIT_RETRIES:
            return status, payload
        if status == 429:
            # Jitter, so several scripts limited at once don't all retry together.
            wait = _retry_after_seconds(resp_headers, payload) + random.uniform(0, 3)
            sys.stderr.write(f"[rate-limit] waiting {wait:.0f}s before retrying\n")
        else:
            wait = 0.0 if os.environ.get("VITRA_DUB_FAST_POLL") == "1" else 2.0 * (2 ** attempt) + random.uniform(0, 1)
            sys.stderr.write(f"[server {status}] retrying in {wait:.0f}s\n")
        time.sleep(wait)

    return status, payload  # unreachable; keeps type checkers content


def get_json(url: str, headers: dict[str, str], timeout: float = 60.0) -> tuple[int, object]:
    return request_json("GET", url, headers, timeout=timeout)


def post_json(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout: float = 120.0,
) -> tuple[int, object]:
    """POST a JSON body and return (status_code, json_payload)."""
    data = json.dumps(body).encode("utf-8")
    return request_json("POST", url, headers, body=data, content_type="application/json", timeout=timeout)


def put_json(
    url: str,
    headers: dict[str, str],
    body: dict,
    timeout: float = 120.0,
) -> tuple[int, object]:
    data = json.dumps(body).encode("utf-8")
    return request_json("PUT", url, headers, body=data, content_type="application/json", timeout=timeout)


def put_file(
    url: str,
    headers: dict[str, str],
    file_path,
    timeout: float = 600.0,
) -> int:
    """PUT raw file bytes (a presigned S3 upload). Returns the status code.

    The presign bakes the headers into the signature, so send back EXACTLY the
    headers the server handed over — no auth header, no extras, or S3 rejects
    the signature.
    """
    with open(file_path, "rb") as fh:
        data = fh.read()
    req = urllib.request.Request(url, data=data, method="PUT")
    for key, value in headers.items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status
    except urllib.error.HTTPError as e:
        return e.code
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise NetworkError(humanize(e)) from e


def download_to_file(
    url: str,
    dest: Path,
    max_bytes: int | None = None,
    timeout: float = 120.0,
) -> int:
    """Stream a URL to `dest`, aborting mid-stream once `max_bytes` is exceeded.

    `max_bytes=None` means NO cap — used where the API itself imposes no size
    limit (video dubbing), so the skill does not invent one the product does
    not have. Pass a number where a real limit exists (the image APIs).

    Returns the byte count on success. Raises NetworkError on connection
    failure, ValueError when the response is not 2xx or the size cap is hit.
    """
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if resp.status // 100 != 2:
                raise ValueError(f"source URL returned HTTP {resp.status}")
            written = 0
            with dest.open("wb") as fh:
                while True:
                    chunk = resp.read(1 << 16)
                    if not chunk:
                        break
                    written += len(chunk)
                    if max_bytes is not None and written > max_bytes:
                        raise ValueError(
                            f"source exceeds the {max_bytes} byte cap"
                        )
                    fh.write(chunk)
            return written
    except urllib.error.HTTPError as e:
        raise ValueError(f"source URL returned HTTP {e.code}") from e
    except (urllib.error.URLError, socket.timeout, ConnectionError) as e:
        raise NetworkError(humanize(e)) from e


def post_multipart_json(
    url: str,
    headers: dict[str, str],
    field_name: str,
    file_path: Path,
    fields: dict[str, str] | None = None,
    timeout: float = 600.0,
) -> tuple[int, object]:
    """POST one file (plus optional text fields) as multipart/form-data.

    Stdlib has no builder for this. `field_name` is the file part the API
    expects (e.g. `files`, `file`, `image`); `fields` are extra text parts.
    Returns (status_code, json_payload).
    """
    boundary = "----vitraSkill" + secrets.token_hex(16)
    filename = file_path.name
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    data = file_path.read_bytes()

    parts: list[bytes] = []
    for key, value in (fields or {}).items():
        parts += [
            f"--{boundary}\r\n".encode(),
            f'Content-Disposition: form-data; name="{key}"\r\n\r\n'.encode(),
            str(value).encode(),
            b"\r\n",
        ]
    parts += [
        f"--{boundary}\r\n".encode(),
        (
            f'Content-Disposition: form-data; name="{field_name}"; '
            f'filename="{filename}"\r\n'
        ).encode(),
        f"Content-Type: {mime}\r\n\r\n".encode(),
        data,
        f"\r\n--{boundary}--\r\n".encode(),
    ]
    body = b"".join(parts)
    return request_json(
        "POST",
        url,
        headers,
        body=body,
        content_type=f"multipart/form-data; boundary={boundary}",
        timeout=timeout,
    )
