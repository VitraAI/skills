"""Browser sign-in (login.py) against a fake Vitra: the PKCE round trip, the
token every script then sends, renewal, and signing out. Run from the repo root:

    python3 -m unittest discover -s tests/sign-in
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlencode, urlparse

sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "brand-kit" / "scripts"


class FakeVitra:
    """Just enough of the OAuth server and API for a sign-in."""

    def __init__(self) -> None:
        self.codes: dict[str, dict] = {}
        self.refreshes = 0
        self.revoked: list[str] = []
        self.seen_auth: list[str] = []
        self.redirect = "http://127.0.0.1/callback"
        self.token_down = False
        self.wiped = 0
        self.lock = threading.Lock()
        fake = self

        class H(BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _json(self, status, obj):
                data = json.dumps(obj).encode()
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

            def do_GET(self):  # noqa: N802
                url = urlparse(self.path)
                q = {k: v[0] for k, v in parse_qs(url.query).items()}
                if url.path == "/.well-known/vitra-agent":
                    return self._json(200, {
                        "client_id": "agent-client",
                        "authorization_endpoint": f"{fake.base}/api/auth/oauth2/authorize",
                        "token_endpoint": f"{fake.base}/api/auth/oauth2/token",
                        "redirect_uri": fake.redirect,
                    })
                if url.path == "/api/auth/oauth2/authorize":
                    # The user signs in and picks an org; the server redirects.
                    fake.codes["the-code"] = q
                    self.send_response(302)
                    self.send_header("Location", q["redirect_uri"] + "?" + urlencode(
                        {"code": "the-code", "state": q["state"]}))
                    self.end_headers()
                    return
                auth = self.headers.get("Authorization") or ""
                fake.seen_auth.append(auth)
                if not auth.startswith("Bearer uvo_"):
                    return self._json(401, {"message": "no"})
                if url.path == "/api/auth/organization/get-full-organization":
                    return self._json(200, {"name": "Acme Studio", "id": "org-1"})
                if url.path == "/api/auth/get-session":
                    return self._json(200, {"user": {"email": "ana@acme.test", "id": "u1"}})
                if url.path == "/v1/agent/tools":
                    return self._json(200, {"tools": []})
                return self._json(404, {"message": "no route"})

            def do_POST(self):  # noqa: N802
                n = int(self.headers.get("Content-Length") or 0)
                form = {k: v[0] for k, v in parse_qs(self.rfile.read(n).decode()).items()}
                if self.path.endswith("/oauth2/revoke"):
                    fake.revoked.append(form.get("token", ""))
                    return self._json(200, {})
                if form.get("grant_type") == "authorization_code":
                    asked = fake.codes.get(form.get("code", ""))
                    challenge = base64.urlsafe_b64encode(hashlib.sha256(
                        form.get("code_verifier", "").encode()).digest()).rstrip(b"=").decode()
                    if not asked or asked["code_challenge"] != challenge \
                            or asked["redirect_uri"] != form.get("redirect_uri") \
                            or form.get("client_id") != "agent-client":
                        return self._json(400, {"error_description": "bad exchange"})
                    return self._json(200, {"access_token": "uvo_first", "refresh_token": "r1",
                                            "expires_in": 3600})
                if form.get("grant_type") == "refresh_token":
                    if fake.token_down:
                        return self._json(503, {})
                    with fake.lock:
                        fake.refreshes += 1
                        if form.get("refresh_token") != "r1":
                            # Vitra (Better Auth) treats reuse as theft: all tokens die.
                            fake.wiped += 1
                            return self._json(400, {"error": "invalid_grant"})
                        time.sleep(0.2)  # widen the race window
                        return self._json(200, {"access_token": "uvo_second", "refresh_token": "r2",
                                                "expires_in": 3600})
                return self._json(400, {})

        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), H)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()


class LoginTest(unittest.TestCase):
    def setUp(self) -> None:
        self.fake = FakeVitra()
        self.home = tempfile.mkdtemp()
        self.env = {**os.environ, "VITRA_UNIVERSE_BASE_URL": self.fake.base,
                    "VITRA_HOME": self.home, "BROWSER": "true",
                    "VITRA_SKILLS_NO_UPDATE_CHECK": "1"}
        self.env.pop("VITRA_UNIVERSE_API_KEY", None)

    def tearDown(self) -> None:
        self.fake.httpd.shutdown()

    def run_script(self, name: str, *args: str) -> dict:
        out = subprocess.run([sys.executable, str(SCRIPTS / name), *args], env=self.env,
                             capture_output=True, text=True, timeout=60, cwd=self.home)
        return json.loads(out.stdout.strip().splitlines()[-1])

    def sign_in(self) -> None:
        started = self.run_script("login.py")
        self.assertEqual(started["status"], "waiting_for_browser")
        # The "browser": follow the sign-in link to the loopback helper.
        with urllib.request.urlopen(started["sign_in_url"], timeout=30) as res:
            self.assertIn(b"signed in", res.read())
        for _ in range(100):
            if self.run_script("login.py", "--status")["status"] == "signed_in":
                return
            time.sleep(0.1)
        self.fail("never signed in")

    def store(self) -> dict:
        return json.loads((Path(self.home) / "universe-signin.json").read_text())[self.fake.base]

    def test_not_signed_in_says_how(self) -> None:
        out = self.run_script("check_access.py") if (SCRIPTS / "check_access.py").exists() \
            else self.run_script("vitra.py", "call", "get_credits", "{}")
        self.assertEqual(out["error"]["code"], "AUTH_MISSING")
        link = out["error"]["sign_in_url"]
        self.assertTrue(link.startswith(self.fake.base + "/api/auth/oauth2/authorize?"))
        self.assertIn(link, out["error"]["ask"])
        self.assertIn("--finish", out["error"]["next_action"])
        # A second try while that sign-in waits hands out the same link.
        again = self.run_script("vitra.py", "call", "get_credits", "{}")
        self.assertEqual(again["error"]["sign_in_url"], link)
        # Following it signs this machine in.
        with urllib.request.urlopen(link, timeout=30) as res:
            self.assertIn(b"signed in", res.read())
        self.assertEqual(self.run_script("login.py", "--status")["status"], "signed_in")

    def test_sign_in_then_scripts_use_the_token(self) -> None:
        self.sign_in()
        status = self.run_script("login.py", "--status")
        self.assertEqual((status["organization"], status["user"]), ("Acme Studio", "ana@acme.test"))
        path = Path(self.home) / "universe-signin.json"
        self.assertEqual(path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn("verifier", path.read_text())

        self.run_script("vitra.py", "tools")
        self.assertEqual(self.fake.seen_auth[-1], "Bearer uvo_first")

    def test_an_expired_token_is_renewed_once(self) -> None:
        self.sign_in()
        entry = self.store()
        entry["expires_at"] = 0
        (Path(self.home) / "universe-signin.json").write_text(json.dumps({self.fake.base: entry}))
        self.run_script("vitra.py", "tools")
        self.assertEqual(self.fake.seen_auth[-1], "Bearer uvo_second")
        self.assertEqual(self.store()["refresh_token"], "r2")
        self.run_script("vitra.py", "tools")
        self.assertEqual(self.fake.refreshes, 1)

    def test_an_api_key_wins_and_logout_forgets(self) -> None:
        self.sign_in()
        self.env["VITRA_UNIVERSE_API_KEY"] = "uvk_test"
        self.assertEqual(self.run_script("login.py", "--status")["status"], "api_key")
        del self.env["VITRA_UNIVERSE_API_KEY"]
        self.assertEqual(self.run_script("login.py", "--logout")["status"], "signed_out")
        self.assertEqual(self.fake.revoked, ["r1", "uvo_first"])
        self.assertEqual(self.run_script("login.py", "--status")["status"], "not_signed_in")


    def expire(self) -> None:
        entry = self.store()
        entry["expires_at"] = 0
        (Path(self.home) / "universe-signin.json").write_text(json.dumps({self.fake.base: entry}))

    def test_parallel_scripts_renew_once(self) -> None:
        self.sign_in()
        self.expire()
        procs = [subprocess.Popen([sys.executable, str(SCRIPTS / "vitra.py"), "tools"], env=self.env,
                                  stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=self.home)
                 for _ in range(4)]
        for p in procs:
            p.wait(timeout=60)
        self.assertEqual((self.fake.refreshes, self.fake.wiped), (1, 0))
        self.assertEqual(self.store()["access_token"], "uvo_second")

    def test_an_outage_is_not_a_sign_out(self) -> None:
        self.sign_in()
        self.expire()
        self.fake.token_down = True
        out = self.run_script("vitra.py", "tools")
        self.assertEqual((out["error"]["code"], out["error"]["retryable"]), ("NETWORK_ERROR", True))
        self.assertEqual(self.store()["refresh_token"], "r1")  # still signed in

    def test_a_stray_callback_does_not_end_the_sign_in(self) -> None:
        started = self.run_script("login.py")
        port = urlparse(parse_qs(urlparse(started["sign_in_url"]).query)["redirect_uri"][0]).port
        for bad in ("state=wrong&code=evil", "error=access_denied", "state=wrong"):
            with self.assertRaises(urllib.error.HTTPError) as caught:
                urllib.request.urlopen(f"http://127.0.0.1:{port}/callback?{bad}", timeout=10)
            self.assertEqual(caught.exception.code, 400)
        self.assertEqual(self.run_script("login.py", "--status")["status"], "waiting_for_browser")
        with urllib.request.urlopen(started["sign_in_url"], timeout=30) as res:
            self.assertIn(b"signed in", res.read())
        self.assertEqual(self.run_script("login.py", "--status")["status"], "signed_in")

    def test_a_doubled_callback_still_says_signed_in(self) -> None:
        started = self.run_script("login.py")
        with urllib.request.urlopen(started["sign_in_url"], timeout=30) as res:
            first = res.geturl()
        pages: list[bytes] = []

        def hit() -> None:
            with urllib.request.urlopen(first, timeout=30) as res:
                pages.append(res.read())

        # The first visit already signed in; two more copies of the same
        # callback must show the same outcome, not "invalid code".
        threads = [threading.Thread(target=hit) for _ in range(2)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        self.assertTrue(all(b"signed in" in p for p in pages), pages)
        self.assertEqual(self.run_script("login.py", "--status")["status"], "signed_in")

    def test_finish_from_a_pasted_address_when_the_browser_cannot_reach_us(self) -> None:
        started = self.run_script("login.py")
        self.assertIn("--finish", started["next_action"])

        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *a, **k):
                return None
        opener = urllib.request.build_opener(NoRedirect)
        try:
            opener.open(started["sign_in_url"], timeout=30)
            self.fail("expected the sign-in redirect")
        except urllib.error.HTTPError as e:  # 302 → the callback address
            address = e.headers["Location"]
        bad = self.run_script("login.py", "--finish", address.replace("state=", "state=x"))
        self.assertEqual(bad["error"]["code"], "SIGNIN_MISMATCH")
        done = self.run_script("login.py", "--finish", address)
        self.assertEqual(done["status"], "signed_in")
        again = self.run_script("login.py", "--finish", address)  # the plan is used up
        self.assertEqual(again["error"]["code"], "NO_SIGNIN_STARTED")

    def test_only_listens_on_this_machine(self) -> None:
        self.fake.redirect = "http://0.0.0.0/callback"
        out = self.run_script("login.py")
        self.assertEqual(out["status"], "failed")


if __name__ == "__main__":
    unittest.main()
