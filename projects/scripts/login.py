#!/usr/bin/env python3
"""Sign in to Vitra from the browser — no API key to copy.

The same sign-in an MCP connector uses: the browser opens Vitra, the user
signs in and picks an organization, and this machine gets a token for that
organization, acting with the user's own role. It renews itself for 30 days of
disuse; after that, sign in again.

  login.py              open the sign-in page; returns at once (see below)
  login.py --status     who is signed in, in which organization
  login.py --logout     forget this machine's sign-in

The command returns straight away with `waiting_for_browser` while a small
helper waits in the background (up to 10 minutes) for the browser to come
back to 127.0.0.1 — so an agent's command timeout can't cut the sign-in off.
Tell the user to finish in the browser, then run `--status`.

No browser on this machine (a server, a container)? Use an organization API
key instead: VITRA_UNIVERSE_API_KEY. A key, when set, is used over a sign-in.

Prints JSON. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import base64
import hashlib
import html
import json
import os
import secrets
import subprocess
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402

WAIT_SECONDS = 600
SCOPES = "openid profile email offline_access"


def _pending_file() -> Path:
    return _common.signin_file().with_name("universe-signin.pending.json")


def _get_json(url: str, headers: dict | None = None) -> tuple[int, object]:
    req = urllib.request.Request(url, headers={"Accept": "application/json", **(headers or {})})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            return res.status, json.loads(res.read().decode("utf-8") or "null")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read().decode("utf-8") or "null")
        except ValueError:
            return e.code, None
    except (urllib.error.URLError, OSError) as e:
        _common.die(_common.EXIT_API_ERROR, f"Network error: couldn't reach Vitra ({e}).")
        return 0, None


def _out(obj: dict) -> int:
    print(json.dumps(obj))
    return 0


# ── Sign in ──────────────────────────────────────────────────────────────────

def start() -> int:
    base = _common.base_url()
    status, meta = _get_json(f"{base}/.well-known/vitra-agent")
    if status != 200 or not isinstance(meta, dict) or not meta.get("client_id"):
        _common.die(
            _common.EXIT_API_ERROR,
            "This Vitra server doesn't offer browser sign-in for skills yet. "
            f"Use an organization API key instead ({_common.ENV_VAR}).",
            error_code="SIGNIN_UNAVAILABLE",
        )

    # The sign-in and token endpoints must belong to the Vitra server this
    # machine is set up for: a tampered answer can't send the code elsewhere.
    for key in ("authorization_endpoint", "token_endpoint"):
        if not _same_site(meta.get(key), base):
            _common.die(_common.EXIT_API_ERROR,
                        "The server's sign-in details point somewhere else; not signing in.",
                        error_code="SIGNIN_UNTRUSTED", retryable=False)

    verifier = secrets.token_urlsafe(64)
    plan = {
        "base": base,
        "client_id": meta["client_id"],
        "authorization_endpoint": meta["authorization_endpoint"],
        "token_endpoint": meta["token_endpoint"],
        "redirect_uri": meta.get("redirect_uri") or "http://127.0.0.1/callback",
        "verifier": verifier,
        "state": secrets.token_urlsafe(24),
    }
    pending = _pending_file()
    pending.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    pending.unlink(missing_ok=True)

    # The helper binds a free port, writes the sign-in URL to the pending
    # file, and waits for the browser. Detached, so it outlives this command.
    popen: dict = {"stdin": subprocess.PIPE, "stdout": subprocess.DEVNULL,
                   "stderr": subprocess.DEVNULL, "close_fds": True}
    if os.name == "nt":
        popen["creationflags"] = 0x00000008 | 0x00000200  # DETACHED | NEW_GROUP
    else:
        popen["start_new_session"] = True
    child = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), "--serve"], **popen)
    assert child.stdin is not None
    # Kept owner-only so `--finish` can complete the sign-in when the browser
    # can't reach this machine's helper (an agent sandbox, a remote shell).
    _common.write_private(_plan_file(), {**plan, "created_at": int(time.time())})
    child.stdin.write(json.dumps(plan).encode())
    child.stdin.close()

    url = None
    for _ in range(100):
        state = _read_pending()
        if state.get("url"):
            url = state["url"]
            break
        if state.get("status") == "failed":
            break
        time.sleep(0.05)
    if not url:
        _common.die(_common.EXIT_API_ERROR,
                    "Couldn't start the sign-in helper on this machine "
                    f"({_read_pending().get('message') or 'no free local port'}).")

    opened = False
    try:
        import webbrowser

        opened = webbrowser.open(url)
    except Exception:  # noqa: BLE001 — no browser is a normal case here
        opened = False
    sys.stderr.write(f"Sign in to Vitra in your browser: {url}\n")
    return _out({
        "status": "waiting_for_browser",
        "browser_opened": opened,
        "sign_in_url": url,
        "next_action": (
            ("A Vitra sign-in tab opened. " if opened else
             "Give the user this sign-in link to open: sign_in_url. ")
            + "Ask them to sign in and pick an organization there, then run "
              "login.py --status. The link works for 10 minutes. If the browser then "
              "shows \"site can't be reached\" (this agent runs in a sandbox), ask the "
              "user to copy the full address from the browser's address bar and run "
              "login.py --finish '<that address>'."
        ),
    })


def _plan_file() -> Path:
    return _common.signin_file().with_name("universe-signin.plan.json")


def finish(address: str) -> int:
    """Complete a sign-in from the callback address the browser couldn't open."""
    try:
        plan = json.loads(_plan_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        _common.die(_common.EXIT_AUTH_MISSING, "No sign-in in progress here: run login.py first.",
                    error_code="NO_SIGNIN_STARTED", retryable=False)
        return 1
    if time.time() - int(plan.get("created_at") or 0) > WAIT_SECONDS:
        _plan_file().unlink(missing_ok=True)
        _common.die(_common.EXIT_AUTH_MISSING, "That sign-in expired: run login.py again.",
                    error_code="SIGNIN_EXPIRED", retryable=False)
    url = urllib.parse.urlsplit(address.strip())
    q = dict(urllib.parse.parse_qsl(url.query))
    if url.hostname not in LOOPBACK or q.get("state") != plan.get("state") or not q.get("code"):
        _common.die(_common.EXIT_AUTH_MISSING,
                    "That isn't the address from this sign-in. Copy the whole address bar "
                    "of the \"site can't be reached\" page and try again.",
                    error_code="SIGNIN_MISMATCH", retryable=False)
    redirect_uri = f"{url.scheme}://{url.hostname}:{url.port}{url.path}" if url.port \
        else f"{url.scheme}://{url.hostname}{url.path}"
    result = _exchange(plan, q["code"], redirect_uri)
    _plan_file().unlink(missing_ok=True)
    if result.get("status") != "signed_in":
        _common.die(_common.EXIT_AUTH_MISSING, result.get("message", "Sign-in didn't finish."),
                    error_code="SIGNIN_FAILED", retryable=False)
    _write_pending(result)
    return status()


def _same_site(url: object, base: str) -> bool:
    """https on the server's own host or a sibling under the same parent
    domain (api.x.vitra.ai ↔ app.x.vitra.ai); http only for localhost."""
    if not isinstance(url, str):
        return False
    u, b = urllib.parse.urlsplit(url), urllib.parse.urlsplit(base)
    if b.hostname in ("localhost", "127.0.0.1"):
        return u.scheme in ("http", "https") and bool(u.hostname)
    if u.scheme != "https" or not u.hostname or not b.hostname:
        return False
    parent = b.hostname.split(".", 1)[1] if b.hostname.count(".") >= 2 else b.hostname
    return u.hostname == b.hostname or u.hostname.endswith("." + parent)


def _read_pending() -> dict:
    try:
        data = json.loads(_pending_file().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def _write_pending(data: dict) -> None:
    _common.write_private(_pending_file(), data)


_PAGE = """<!doctype html><meta charset="utf-8"><title>Vitra</title>
<body style="font:16px system-ui;margin:15vh auto;max-width:28rem;padding:0 1rem;text-align:center">
<h1 style="font-size:1.4rem">{title}</h1><p>{body}</p></body>"""


LOOPBACK = ("127.0.0.1", "localhost")


def serve() -> int:
    """The background helper: catch the browser's return and keep the token."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    plan = json.loads(sys.stdin.read())
    redirect = urllib.parse.urlsplit(plan["redirect_uri"])
    if redirect.scheme != "http" or redirect.hostname not in LOOPBACK:
        # Only ever listen on this machine, whatever the server advertises.
        _write_pending({"status": "failed",
                        "message": "The server asked for a sign-in address that isn't this machine."})
        return 1
    result: dict = {}
    finish_lock = threading.Lock()

    class Handler(BaseHTTPRequestHandler):
        timeout = 5  # an idle connection (a browser preconnect) can't stall the helper

        def log_message(self, *args):  # silence the default stderr log
            pass

        def _page(self, status: int, title: str, body: str) -> None:
            page = _PAGE.format(title=html.escape(title), body=html.escape(body)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(page)))
            self.end_headers()
            self.wfile.write(page)

        def do_GET(self):  # noqa: N802
            parts = urllib.parse.urlsplit(self.path)
            q = dict(urllib.parse.parse_qsl(parts.query))
            if parts.path != redirect.path or q.get("state") != plan["state"]:
                # Not our sign-in's reply (another tab, a local port scan):
                # ignore it and keep waiting for the real one.
                self._page(400, "Not a Vitra sign-in", "This link isn't part of a sign-in in progress.")
                return
            # Browsers may send the same callback twice at once. The code works
            # only once, so the first request exchanges it and any other waits
            # and shows that same outcome, never a false "invalid code".
            with finish_lock:
                if not result:
                    if _read_pending().get("pid") != os.getpid():
                        result.update(status="superseded")
                    elif q.get("error"):
                        result.update(status="failed",
                                      message=q.get("error_description") or "Sign-in was cancelled.")
                    else:
                        result.update(_exchange(plan, q.get("code", ""), self.server.redirect_uri))
                        _plan_file().unlink(missing_ok=True)
                    if result.get("status") != "superseded":
                        _write_pending(result)  # before the reply, so --status sees it at once
            if result.get("status") == "superseded":
                self._page(200, "Sign-in replaced",
                           "A newer sign-in was started on this machine; finish that one instead.")
                return
            ok = result.get("status") == "signed_in"
            self._page(200, "You're signed in" if ok else "Sign-in didn't finish",
                       "Go back to your agent; it can use Vitra now. You can close this tab."
                       if ok else result.get("message", "Please try again."))

    try:
        httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    except OSError as e:
        _write_pending({"status": "failed", "message": str(e)})
        return 1
    httpd.daemon_threads = True
    port = httpd.server_address[1]
    httpd.redirect_uri = f"http://{redirect.hostname}:{port}{redirect.path}"
    challenge = base64.urlsafe_b64encode(
        hashlib.sha256(plan["verifier"].encode()).digest()).rstrip(b"=").decode()
    url = plan["authorization_endpoint"] + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": plan["client_id"],
        "redirect_uri": httpd.redirect_uri,
        "scope": SCOPES,
        "state": plan["state"],
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    })
    _write_pending({"status": "waiting", "url": url, "pid": os.getpid()})

    deadline = time.time() + WAIT_SECONDS
    httpd.timeout = 1
    while not result and time.time() < deadline:
        httpd.handle_request()
    time.sleep(0.2)  # let the reply page finish sending
    httpd.server_close()
    if result.get("status") == "superseded" or _read_pending().get("pid") != os.getpid():
        return 0  # a newer sign-in started meanwhile; its helper owns the file
    _write_pending(result or {"status": "expired",
                              "message": "Nobody finished signing in within 10 minutes."})
    return 0


def _exchange(plan: dict, code: str, redirect_uri: str) -> dict:
    body = urllib.parse.urlencode({
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": redirect_uri,
        "client_id": plan["client_id"],
        "code_verifier": plan["verifier"],
    }).encode()
    req = urllib.request.Request(
        plan["token_endpoint"], data=body, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            tok = json.loads(res.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("error_description")
        except (ValueError, AttributeError):
            detail = None
        return {"status": "failed", "message": detail or f"Vitra refused the sign-in ({e.code})."}
    except (urllib.error.URLError, OSError, ValueError):
        return {"status": "failed", "message": "Couldn't reach Vitra to finish signing in."}
    if not tok.get("access_token"):
        return {"status": "failed", "message": "Vitra sent no token back."}
    _common.write_signin({
        "client_id": plan["client_id"],
        "token_endpoint": plan["token_endpoint"],
        "access_token": tok["access_token"],
        "refresh_token": tok.get("refresh_token"),
        "expires_at": int(time.time()) + int(tok.get("expires_in") or 3600),
    }, plan["base"])
    return {"status": "signed_in"}


# ── Status / sign out ────────────────────────────────────────────────────────

def status() -> int:
    kind = _common.credential()
    pending = _read_pending()
    if kind == "api_key":
        return _out({"status": "api_key",
                     "message": f"Using the API key in {_common.ENV_VAR}; it wins over a sign-in.",
                     "next_action": None})
    if kind == "none":
        if pending.get("status") == "waiting":
            return _out({"status": "waiting_for_browser", "sign_in_url": pending.get("url"),
                         "next_action": "The user hasn't finished signing in yet. Ask them to, then check again."})
        if pending.get("status") in ("failed", "expired"):
            return _out({"status": "not_signed_in", "reason": pending.get("message"),
                         "next_action": "Run login.py again to start a new sign-in."})
        return _out({"status": "not_signed_in", "next_action": "Run login.py to sign in."})

    token = _common.signed_in_token()
    if not token:
        return _out({"status": "not_signed_in", "reason": "The sign-in has ended.",
                     "next_action": "Run login.py to sign in again."})
    base = _common.base_url()
    auth = {"Authorization": f"Bearer {token}"}
    code, org = _get_json(f"{base}/api/auth/organization/get-full-organization", auth)
    _, sess = _get_json(f"{base}/api/auth/get-session", auth)
    if code == 401:
        return _out({"status": "not_signed_in", "reason": "Vitra no longer accepts this sign-in.",
                     "next_action": "Run login.py to sign in again."})
    if code != 200 or not isinstance(org, dict):
        # Signed in on this machine, but Vitra didn't say who: don't guess.
        return _out({"status": "signed_in", "server": base,
                     "unverified": f"Vitra didn't answer ({code}); it may be restarting.",
                     "next_action": "Try login.py --status again in a minute."})
    user = (sess or {}).get("user") if isinstance(sess, dict) else None
    return _out({
        "status": "signed_in",
        "organization": (org or {}).get("name") if isinstance(org, dict) else None,
        "user": (user or {}).get("email"),
        "next_action": None,
    })


def logout() -> int:
    entry = _common.read_signins().get(_common.base_url())
    if isinstance(entry, dict):
        # Best effort: revoke both tokens on the server so they die everywhere,
        # not only on this machine.
        revoke = entry.get("token_endpoint", "").rsplit("/", 1)[0] + "/revoke"
        for hint in ("refresh_token", "access_token"):
            if not entry.get(hint):
                continue
            body = urllib.parse.urlencode({"token": entry[hint], "token_type_hint": hint,
                                           "client_id": entry.get("client_id", "")}).encode()
            try:
                urllib.request.urlopen(urllib.request.Request(
                    revoke, data=body, method="POST",
                    headers={"Content-Type": "application/x-www-form-urlencoded"}),
                    timeout=15).close()
            except (urllib.error.URLError, OSError):
                pass
    _common.write_signin(None)
    _pending_file().unlink(missing_ok=True)
    return _out({"status": "signed_out", "next_action": None})


def main() -> int:
    p = argparse.ArgumentParser(description="Sign in to Vitra from the browser.")
    g = p.add_mutually_exclusive_group()
    g.add_argument("--status", action="store_true", help="who is signed in, where")
    g.add_argument("--logout", action="store_true", help="forget this machine's sign-in")
    g.add_argument("--serve", action="store_true", help=argparse.SUPPRESS)
    g.add_argument("--finish", metavar="ADDRESS",
                   help="finish with the browser's address when it couldn't reach this machine")
    a = p.parse_args()
    if a.serve:
        return serve()
    if a.finish:
        return finish(a.finish)
    if a.status:
        return status()
    if a.logout:
        return logout()
    return start()


if __name__ == "__main__":
    sys.exit(main())
