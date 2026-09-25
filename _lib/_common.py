"""Shared config + auth for every Vitra skill's scripts.

Single source: `sync-lib.sh` copies this file into each skill's
`scripts/_common.py` (the dub skill's `scripts/_core.py`). Edit it here only,
then run the sync.

The API key is the only secret; everything else is fixed here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

# Vitra Universe server. Production unless overridden, so a real user needs
# nothing but an API key.
#
# ORIGIN ONLY — the `/v1` prefix lives in each script's path constants
# (`/v1/galaxy/...`), so it must not be repeated here.
#
# `VITRA_UNIVERSE_BASE_URL` overrides it. That exists for development against a
# local or staging server: until the org-scoped API-key endpoints ship to
# production, testing REQUIRES the override, e.g.
#   export VITRA_UNIVERSE_BASE_URL=http://localhost:4040
BASE_URL = "https://universe-api.vitra.ai"
BASE_URL_VAR = "VITRA_UNIVERSE_BASE_URL"

EXIT_OK = 0
EXIT_AUTH_MISSING = 2
EXIT_AUTH_REJECTED = 3
EXIT_API_ERROR = 4
EXIT_TIMEOUT = 5
EXIT_DOWNLOAD = 6


def base_url() -> str:
    """Server origin — the override if set, else production.

    Read from the environment first, then a `.env` beside the skill, the same
    way the API key is resolved.
    """
    raw = (
        os.environ.get(BASE_URL_VAR) or _from_env_file(BASE_URL_VAR) or BASE_URL
    ).strip()
    if not raw.startswith(("http://", "https://")):
        raw = "https://" + raw
    raw = raw.rstrip("/")
    # Absorb a trailing `/v1`: the request paths already carry it, and the
    # documented endpoint people copy ends in `/v1`.
    if raw.endswith("/v1"):
        raw = raw[:-3]
    return raw.rstrip("/")


ENV_VAR = "VITRA_UNIVERSE_API_KEY"


def _from_env_file(var_name: str = "VITRA_UNIVERSE_API_KEY") -> str | None:
    """Read the key from a `.env` beside the skill, if there is one.

    The environment wins. This exists because the skill ships a `.env.sample`
    and the README calls it the template — without this, a user who follows
    those instructions exactly still gets "missing env var", which is the
    setup step failing silently for the one reason they cannot guess.

    Deliberately minimal: `KEY=value`, optional `export ` prefix, optional
    quotes, `#` comments. No dependency on python-dotenv (stdlib only).
    """
    path = Path(__file__).resolve().parent.parent / ".env"
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        name, sep, value = line.partition("=")
        if sep and name.strip() == var_name:
            return value.strip().strip("\"'") or None
    return None


def api_key() -> str:
    key = os.environ.get(ENV_VAR) or _from_env_file(ENV_VAR)
    if not key:
        sys.stderr.write(
            f"Missing {ENV_VAR}.\n"
            "\n"
            "This skill needs a Vitra API key (starts `uvk_`). Ask whoever "
            "administers your Vitra organization for one — a key is bound to a "
            "single organization and carries its creator's permissions there.\n"
            "\n"
            "Then make it available in ONE of these ways:\n"
            f"  * export {ENV_VAR}=uvk_...        (the agent must inherit this)\n"
            f"  * put {ENV_VAR}=uvk_... in a `.env` beside this skill\n"
            "\n"
            "Note: exporting in your terminal does NOT reach a desktop or "
            "hosted agent — it must be set in the environment that agent runs "
            "in.\n"
        )
        sys.exit(EXIT_AUTH_MISSING)
    return key


def headers() -> dict[str, str]:
    """Auth headers for every request.

    The key is bound to one organization at creation, so the server resolves
    the org from the key itself — no `organizationId` header to send.
    """
    return {"x-api-key": api_key(), "X-Client-Source": "agent"}


# Error codes for the JSON a failing script prints, by exit code. `retryable`
# says whether re-running the SAME command can succeed without changing
# anything (a timeout can; a rejected key cannot).
_ERROR_CODES = {
    EXIT_AUTH_MISSING: ("AUTH_MISSING", False),
    EXIT_AUTH_REJECTED: ("AUTH_REJECTED", False),
    EXIT_API_ERROR: ("API_ERROR", False),
    EXIT_TIMEOUT: ("TIMEOUT", True),
    EXIT_DOWNLOAD: ("DOWNLOAD_FAILED", True),
}


def die(
    code: int,
    msg: str,
    error_code: str | None = None,
    retryable: bool | None = None,
    **extra: object,
) -> None:
    """Fail with a readable line on stderr AND a structured one on stdout.

    stdout always carries exactly one JSON object, success or failure, so the
    agent parses one shape:
      {"status": "failed", "error": {"code", "message", "retryable", ...},
       "request_id": "..."}
    The request id is the server's, for support; it holds no secret.
    """
    import json

    default_code, default_retryable = _ERROR_CODES.get(code, ("API_ERROR", False))
    import re

    if error_code is None and re.search(r"\((50[0-9])\)", msg):
        # The server failed, not the request: running it again is reasonable.
        default_code, default_retryable = "SERVER_ERROR", True
    if error_code is None and msg.lstrip().lower().startswith("network error"):
        # The request may or may not have reached the server; every command
        # reconciles on a re-run, so running it again is the right move.
        default_code, default_retryable = "NETWORK_ERROR", True
    error = {
        "code": error_code or default_code,
        "message": msg.strip(),
        "retryable": default_retryable if retryable is None else retryable,
        **extra,
    }
    request_id = None
    http = sys.modules.get("_http")
    if http is not None:
        request_id = http.last_request_id()
    sys.stderr.write(msg.rstrip() + "\n")
    print(json.dumps({"status": "failed", "error": error, "request_id": request_id}))
    sys.exit(code)


def api_message(payload: object, fallback: str = "the server rejected the request") -> str:
    """The human-readable reason out of an API error body.

    Nest answers `{message, error, statusCode}` where `message` is a string or
    a list of validation strings. Dumping the raw JSON at a caller shows them
    envelope noise; this returns just the part that says what to fix.
    """
    body = payload if isinstance(payload, dict) else {}
    inner = body.get("data")
    if isinstance(inner, dict) and ("message" in inner or "error" in inner):
        body = inner

    message = body.get("message")
    if isinstance(message, list):
        parts = [str(m).strip() for m in message if str(m).strip()]
        if parts:
            return parts[0] if len(parts) == 1 else "; ".join(parts[:3])
    if isinstance(message, str) and message.strip():
        return message.strip()

    for key in ("error", "detail", "title"):
        value = body.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()

    raw = body.get("_raw")
    if isinstance(raw, str) and raw.strip():
        text = " ".join(raw.split())
        return text[:200] + ("…" if len(text) > 200 else "")
    return fallback


def auth_error(status: int, what: str = "this request") -> str:
    """Actionable text for a 401/403. They are different problems.

    401 = the key itself is not accepted (wrong, revoked, expired).
    403 = the key is valid but its member lacks the permission.

    Rate limiting is NOT a 403: it arrives as 429 with `Retry-After`, and
    `_http.request_json` waits it out and retries, so it rarely surfaces here.
    """
    if status == 401:
        return (
            "Your API key was not accepted. It may be mistyped, revoked, or "
            "expired — ask your Vitra org administrator for a new one."
        )
    if status == 429:
        return (
            "Your API key is sending requests faster than it is allowed to, "
            "even after waiting. Pause for a minute and run the command again "
            "— any job already started keeps running meanwhile."
        )
    return (
        f"Your API key is valid but not allowed to do {what}. The member who "
        "created it lacks that permission in this organization — ask your "
        "Vitra org administrator."
    )


def sha256_file(path: Path) -> str:
    """SHA-256 of a file, streamed so a multi-GB video is never held in memory."""
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def idempotency_key(*parts: object) -> str:
    """A key derived from WHAT the operation is, never random.

    Sent as `Idempotency-Key` on publish / add-language / export. The server
    replays the first response for the same key and body, so a request retried
    after a timeout — or after this process died and was re-run — cannot start
    the work twice. That only works if the retry sends the SAME key, which a
    random key would not; deriving it from the operation makes it rebuildable.
    """
    import hashlib

    joined = "\x1f".join(str(p) for p in parts)
    return "skill-" + hashlib.sha256(joined.encode("utf-8")).hexdigest()[:40]
