"""Shared config + auth for every Vitra skill's scripts.

Single source: `sync-lib.sh` copies this file into each skill's
`scripts/_common.py` (the dub skill's `scripts/_core.py`). Edit it here only,
then run the sync.

Two ways in, both acting in ONE organization with the member's own role:
  * sign in with the browser (`scripts/login.py`) — the token lands in
    ~/.vitra/universe-signin.json and refreshes itself;
  * an organization API key (`VITRA_UNIVERSE_API_KEY`), for machines with no
    browser. A key, when set, wins.
Everything else is fixed here.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

for _stream in (sys.stdout, sys.stderr):
    try:  # Windows consoles default to a legacy code page
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

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

    The environment wins. Skills sign in with `login.py` now; this stays so
    existing installs that keep their API key in a local, gitignored `.env`
    beside SKILL.md keep working.

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


APP_URL_VAR = "VITRA_UNIVERSE_APP_URL"
DEFAULT_APP_URL = "https://universe.vitra.ai"


def _configured_key() -> str | None:
    return os.environ.get(ENV_VAR) or _from_env_file(ENV_VAR)


# ── Browser sign-in (see login.py) ───────────────────────────────────────────
# The token is the same org-pinned OAuth token an MCP connector holds: an hour
# long, renewed here with the 30-day refresh token. Stored per server, so a
# staging sign-in never shadows production.
HOME_VAR = "VITRA_HOME"


def signin_file() -> Path:
    home = os.environ.get(HOME_VAR) or str(Path.home() / ".vitra")
    return Path(home) / "universe-signin.json"


def read_signins() -> dict:
    import json

    try:
        data = json.loads(signin_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def write_private(path: Path, data: object) -> None:
    """Write JSON readable only by this user, atomically.

    A unique temp file per writer, so parallel scripts never trip over each
    other's half-written file; `os.replace` then swaps it in whole.
    """
    import json
    import tempfile
    import time

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=path.name + ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2)
        for attempt in range(20):
            try:
                os.replace(tmp, path)
                return
            except PermissionError:  # Windows: a reader has it open for a moment
                if attempt == 19:
                    raise
                time.sleep(0.05)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class _SigninLock:
    """Exclusive lock on the sign-in file, across processes.

    Needed because Vitra rotates the refresh token on every use and treats a
    second use of an old one as theft: it revokes the whole sign-in. So only
    one script may renew at a time, and the others must pick up its result.
    """

    def __enter__(self):
        path = signin_file().with_name("universe-signin.lock")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self._fh = open(path, "a+b")
        if os.name == "nt":
            import msvcrt
            import time

            while True:
                try:
                    self._fh.seek(0)
                    msvcrt.locking(self._fh.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    time.sleep(0.05)
        else:
            import fcntl

            fcntl.flock(self._fh.fileno(), fcntl.LOCK_EX)
        return self

    def __exit__(self, *exc):
        try:
            if os.name == "nt":
                import msvcrt

                self._fh.seek(0)
                msvcrt.locking(self._fh.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(self._fh.fileno(), fcntl.LOCK_UN)
        finally:
            self._fh.close()
        return False


def write_signin(entry: dict | None, base: str | None = None) -> None:
    """Save (or with None, forget) this server's sign-in. Owner-only file."""
    base = base or base_url()
    with _SigninLock():
        data = read_signins()
        if entry is None:
            data.pop(base, None)
        else:
            data[base] = entry
        write_private(signin_file(), data)


def _refresh(entry: dict) -> tuple[str, dict | None]:
    """Swap the refresh token for a new pair.

    Returns ("ok", entry), ("ended", None) when Vitra refuses the refresh
    token (signed out, expired, revoked), or ("unreachable", None) when the
    answer never came — that is NOT a sign-out.
    """
    import json
    import time
    import urllib.error
    import urllib.parse
    import urllib.request

    body = urllib.parse.urlencode({
        "grant_type": "refresh_token",
        "refresh_token": entry.get("refresh_token", ""),
        "client_id": entry.get("client_id", ""),
    }).encode()
    req = urllib.request.Request(
        entry.get("token_endpoint", ""), data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded",
                 "Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            tok = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return ("ended", None) if e.code in (400, 401) else ("unreachable", None)
    except (urllib.error.URLError, OSError, ValueError):
        return "unreachable", None
    if not tok.get("access_token"):
        return "ended", None
    return "ok", {
        **entry,
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token") or entry.get("refresh_token"),
        "expires_at": int(time.time()) + int(tok.get("expires_in") or 3600),
    }


_SIGNIN_ENDED = False  # set when this run found the sign-in over


def _fresh(entry: object) -> bool:
    import time

    return isinstance(entry, dict) and bool(entry.get("access_token")) and \
        int(entry.get("expires_at") or 0) - 60 > time.time()


def signed_in_token() -> str | None:
    """This server's sign-in token, renewed when due. None if not signed in."""
    base = base_url()
    entry = read_signins().get(base)
    if not isinstance(entry, dict) or not entry.get("access_token"):
        return None
    if _fresh(entry):
        return entry["access_token"]
    with _SigninLock():
        # Another script may have renewed it while this one waited.
        data = read_signins()
        entry = data.get(base)
        if _fresh(entry):
            return entry["access_token"]
        if not isinstance(entry, dict) or not entry.get("refresh_token"):
            return None
        outcome, renewed = _refresh(entry)
        if outcome == "unreachable":
            die(EXIT_API_ERROR,
                "Network error: couldn't reach Vitra to renew your sign-in. "
                "Check the connection and run the command again.",
                error_code="NETWORK_ERROR", retryable=True)
        if renewed is None:
            global _SIGNIN_ENDED
            _SIGNIN_ENDED = True
            data.pop(base, None)
        else:
            data[base] = renewed
        write_private(signin_file(), data)
    return renewed["access_token"] if renewed else None


def credential() -> str:
    """Which credential this run uses: "api_key", "signin" or "none"."""
    if _configured_key():
        return "api_key"
    entry = read_signins().get(base_url())
    return "signin" if isinstance(entry, dict) and entry.get("access_token") else "none"


def _missing() -> None:
    app = (os.environ.get(APP_URL_VAR) or DEFAULT_APP_URL).rstrip("/")
    had = _SIGNIN_ENDED or credential() == "signin"
    # Start the sign-in now, so every agent can hand the user a link at once.
    info = None
    try:
        import login  # vendored next to this file

        info = login.begin(open_browser=False, quiet=True)
    except Exception:  # noqa: BLE001 — fall back to the instructions below
        info = None
    if info:
        url = info["sign_in_url"]
        die(
            EXIT_AUTH_MISSING,
            (f"Your Vitra sign-in for {base_url()} has ended." if had
             else f"Not signed in to Vitra at {base_url()}.")
            + f"\n\nSign in here, then pick your organization:\n  {url}\n\n"
            f"New to Vitra? Sign up first: {app}/auth/sign-up",
            ask=(f"Please sign in to Vitra: open {url} , sign in and pick your "
                 "organization, then tell me when you're done."),
            next_action=(
                "Show the user sign_in_url as a clickable link and wait. When they say "
                "they're done, run scripts/login.py --status, then run this command "
                "again. If their browser shows \"This site can't be reached\", ask them "
                "for the full address in the address bar and run "
                "scripts/login.py --finish '<address>'."),
            sign_in_url=url,
            server=base_url(),
            sign_up=f"{app}/auth/sign-up",
        )
    die(
        EXIT_AUTH_MISSING,
        (f"Your Vitra sign-in for {base_url()} has ended.\n" if had
         else f"Not signed in to Vitra at {base_url()}.\n")
        + "\n"
        "Sign in (opens the browser, then pick an organization):\n"
        "  python3 scripts/login.py\n"
        "\n"
        f"New to Vitra? Sign up first: {app}/auth/sign-up\n"
        "\n"
        f"No browser on this machine? Use an organization API key instead: create one\n"
        f"in Settings -> API keys ({app}/auth/sign-in; owners and admins can), then\n"
        f"set {ENV_VAR}=uvk_... where the agent runs, or in a .env beside SKILL.md.",
        ask=("You need to sign in to Vitra. Shall I open the sign-in page? "
             f"(New to Vitra? Sign up at {app}/auth/sign-up first.)"),
        next_action=("Run scripts/login.py once the user agrees, then run this command again. "
                     f"This machine talks to {base_url()} (VITRA_UNIVERSE_BASE_URL changes it)."),
        server=base_url(),
        sign_in=f"{app}/auth/sign-in",
        sign_up=f"{app}/auth/sign-up",
    )


def api_key() -> str:
    """The configured API key, or the sign-in instructions when there is none."""
    key = _configured_key()
    if key:
        return key
    _missing()
    return ""  # unreachable: die() exits


def headers() -> dict[str, str]:
    """Auth headers for every request.

    A key and a sign-in are each bound to one organization, so the server
    resolves the org from the credential — no `organizationId` header to send.
    """
    key = _configured_key()
    if key:
        return {"x-api-key": key, "X-Client-Source": "agent"}
    token = signed_in_token()
    if token:
        return {"Authorization": f"Bearer {token}", "X-Client-Source": "agent"}
    _missing()
    return {}  # unreachable: die() exits


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


def auth_error(status: int, what: str = "do this") -> str:
    """Actionable text for a 401/403. They are different problems.

    401 = the credential itself is not accepted (wrong, revoked, expired).
    403 = the credential is valid but its member lacks the permission.

    Rate limiting is NOT a 403: it arrives as 429 with `Retry-After`, and
    `_http.request_json` waits it out and retries, so it rarely surfaces here.
    """
    signin = credential() == "signin"
    if status == 401:
        if signin:
            return (
                "Your Vitra sign-in was not accepted — it may have ended, or you "
                "left that organization. Sign in again: python3 scripts/login.py"
            )
        return (
            f"Your API key ({ENV_VAR}) was not accepted by {base_url()}. It may be "
            "mistyped, revoked, expired, or made on another Vitra environment: a key "
            "works only where it was created. It overrides browser sign-in: unset it "
            "to sign in with scripts/login.py instead, or ask your Vitra org "
            "administrator for a new key for this server."
        )
    if status == 429:
        return (
            "Vitra is getting requests faster than it allows, even after waiting. "
            "Pause for a minute and run the command again — any job already "
            "started keeps running meanwhile."
        )
    who = "Your role" if signin else "Your API key is valid but the member who created it"
    return (
        f"{who} is not allowed to {what} in this organization — ask your "
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
