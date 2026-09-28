#!/usr/bin/env python3
"""Use Vitra from any agent: every Vitra feature is a server tool, and this
script only forwards to it. The server does the work, the lookups by name,
the rules and the wording; nothing about Vitra lives here.

  vitra.py tools [--find WORDS]          the tools you may use (name, title)
  vitra.py describe TOOL                 what TOOL does and the arguments it takes
  vitra.py call TOOL [ARGS_JSON] [--intent TEXT] [--toolsets a,b]
                                         run TOOL with a JSON object of arguments
  vitra.py upload PATH                   put a local file in Vitra; prints its asset
  vitra.py download URL --to PATH        save a link a tool returned to a local file

Every command prints ONE JSON object on stdout. On failure:
  {"status": "failed", "error": {"code", "message", "retryable", ...}}
A tool that changes something is never marked retryable after a network error
or timeout: it may have run, so check with the matching status or list tool.

Signing in: `login.py` (browser), or VITRA_UNIVERSE_API_KEY on machines with
no browser. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import mimetypes
import os
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

TOOLS_PATH = "/v1/agent/tools"
MAX_ARGS_BYTES = 256 * 1024


def _out(obj: object) -> int:
    print(json.dumps(obj, ensure_ascii=False))
    return 0


def _headers(toolsets: str | None = None) -> dict[str, str]:
    h = _common.headers()
    if toolsets:
        h["X-MCP-Toolsets"] = toolsets
    return h


def _fail_http(status: int, payload: object, *, wrote: bool) -> None:
    """Explain a non-2xx answer from the tools route and exit."""
    body = payload if isinstance(payload, dict) else {}
    message = _common.api_message(payload)
    if status == 401:
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(401))
    extra = {k: body[k] for k in ("required", "available", "owed", "issues", "retryAfter")
             if k in body}
    if status == 402:
        _common.die(_common.EXIT_API_ERROR, message, error_code="INSUFFICIENT_CREDITS",
                    retryable=False, **extra)
    if status == 403:
        _common.die(_common.EXIT_AUTH_REJECTED, message, error_code="NOT_ALLOWED",
                    retryable=False)
    if status >= 500 or status == 429:
        # A read can simply run again; a change may already have happened.
        _common.die(_common.EXIT_API_ERROR, message,
                    error_code="SERVER_ERROR" if status >= 500 else "RATE_LIMITED",
                    retryable=not wrote, **extra)
    _common.die(_common.EXIT_API_ERROR, message, retryable=False, **extra)


def _request(method: str, path: str, body: object | None = None, *,
             toolsets: str | None = None, wrote: bool = False,
             timeout: float = 300.0) -> object:
    url = _common.base_url() + path
    data = None if body is None else json.dumps(body).encode("utf-8")
    try:
        status, payload = _http.request_json(
            method, url, _headers(toolsets), data,
            "application/json" if data is not None else None, timeout=timeout)
    except _http.NetworkError as e:
        _common.die(
            _common.EXIT_API_ERROR,
            f"Network error: {e}."
            + (" If that tool changes something it may still have run: check its "
               "status or list before trying again." if wrote else ""),
            error_code="NETWORK_ERROR", retryable=not wrote)
    if status // 100 != 2:
        _fail_http(status, payload, wrote=wrote)
    return payload


def _catalog(toolsets: str | None) -> list[dict]:
    payload = _request("GET", TOOLS_PATH, toolsets=toolsets)
    tools = payload.get("tools") if isinstance(payload, dict) else None
    return tools if isinstance(tools, list) else []


# ── Commands ─────────────────────────────────────────────────────────────────

def cmd_tools(a: argparse.Namespace) -> int:
    words = [w.lower() for w in (a.find or "").split() if w]
    rows = []
    for t in _catalog(a.toolsets):
        text = f"{t.get('name', '')} {t.get('title', '')} {t.get('description', '')}".lower()
        if all(w in text for w in words):
            rows.append({"name": t.get("name"), "title": t.get("title"),
                         "changes_something": not t.get("read_only")})
    return _out({"status": "ok", "count": len(rows), "tools": rows[:200],
                 "next_action": "Run `describe TOOL` for its arguments, then `call TOOL`."})


def cmd_describe(a: argparse.Namespace) -> int:
    for t in _catalog(a.toolsets):
        if t.get("name") == a.tool:
            return _out({"status": "ok", "name": t["name"], "title": t.get("title"),
                         "description": t.get("description"),
                         "changes_something": not t.get("read_only"),
                         "destructive": bool(t.get("destructive")),
                         "arguments": t.get("input_schema")})
    _common.die(_common.EXIT_API_ERROR,
                f'No tool called "{a.tool}" is available to you. Run `tools --find ...`.',
                error_code="UNKNOWN_TOOL", retryable=False)
    return 1


def _parse_args(raw: str | None) -> dict:
    if raw is None or raw.strip() == "":
        return {}
    if raw == "-":
        raw = sys.stdin.read()
    if len(raw.encode("utf-8")) > MAX_ARGS_BYTES:
        _common.die(_common.EXIT_API_ERROR, "The arguments are too large (256 KB at most).",
                    error_code="BAD_ARGUMENTS", retryable=False)
    try:
        args = json.loads(raw)
    except ValueError as e:
        _common.die(_common.EXIT_API_ERROR, f"ARGS_JSON is not valid JSON ({e}).",
                    error_code="BAD_ARGUMENTS", retryable=False)
    if not isinstance(args, dict):
        _common.die(_common.EXIT_API_ERROR, "ARGS_JSON must be a JSON object.",
                    error_code="BAD_ARGUMENTS", retryable=False)
    return args


def cmd_call(a: argparse.Namespace) -> int:
    if not a.tool.replace("_", "").isalnum():
        _common.die(_common.EXIT_API_ERROR, "A tool name has only letters, digits and _.",
                    error_code="UNKNOWN_TOOL", retryable=False)
    body: dict = {"args": _parse_args(a.args)}
    if a.intent:
        body["user_intent"] = a.intent[:255]
    # Any call may change something, so a lost answer is never "just retry":
    # the agent checks first (a read can simply run again).
    result = _request("POST", f"{TOOLS_PATH}/{a.tool}", body, toolsets=a.toolsets,
                      wrote=True)
    return _out({"status": "ok", "result": result})


def _call_tool(name: str, args: dict) -> dict:
    out = _request("POST", f"{TOOLS_PATH}/{name}", {"args": args}, wrote=True)
    return out if isinstance(out, dict) else {}


def cmd_upload(a: argparse.Namespace) -> int:
    path = Path(a.path).expanduser()
    if not path.is_file():
        _common.die(_common.EXIT_DOWNLOAD, f"No file at {path}.", error_code="FILE_NOT_FOUND",
                    retryable=False)
    ctype = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    link = _call_tool("create_upload_url", {"file_name": path.name, "content_type": ctype})
    upload_url, key = link.get("upload_url"), link.get("key")
    if not (isinstance(upload_url, str) and upload_url.startswith("https://") and key):
        _common.die(_common.EXIT_API_ERROR, "Vitra gave no usable upload link.",
                    retryable=True)
    size = path.stat().st_size
    with path.open("rb") as fh:
        req = urllib.request.Request(upload_url, data=fh, method="PUT", headers={
            "Content-Type": ctype, "Content-Length": str(size)})
        try:
            with urllib.request.urlopen(req, timeout=max(120.0, size / 1_000_000)) as res:
                ok = res.status // 100 == 2
        except urllib.error.HTTPError as e:
            ok = False
            _common.die(_common.EXIT_API_ERROR, f"The upload was refused ({e.code}).",
                        retryable=True)
        except (urllib.error.URLError, OSError) as e:
            _common.die(_common.EXIT_API_ERROR, f"Network error during upload: {e}.",
                        error_code="NETWORK_ERROR", retryable=True)
    if not ok:
        _common.die(_common.EXIT_API_ERROR, "The upload did not finish.", retryable=True)
    asset = _call_tool("register_upload", {"key": key, "file_name": path.name,
                                           "content_type": ctype})
    return _out({"status": "ok", "file": path.name, "bytes": size, "asset": asset,
                 "next_action": "Pass the asset to the tool that needs the file."})


def cmd_download(a: argparse.Namespace) -> int:
    url = urllib.parse.urlsplit(a.url)
    if url.scheme != "https":
        _common.die(_common.EXIT_DOWNLOAD, "Only https links from Vitra can be downloaded.",
                    retryable=False)
    dest = Path(a.to).expanduser()
    if dest.exists() and dest.is_dir():
        name = Path(urllib.parse.unquote(url.path)).name or "download"
        dest = dest / name
    if dest.exists() and not a.overwrite:
        _common.die(_common.EXIT_DOWNLOAD, f"{dest} already exists; pass --overwrite to replace it.",
                    retryable=False)
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_name(dest.name + ".part")
    try:
        written = _http.download_to_file(a.url, tmp)
    except (_http.NetworkError, ValueError) as e:
        tmp.unlink(missing_ok=True)
        _common.die(_common.EXIT_DOWNLOAD, f"The download failed: {e}. The link may have "
                    "expired: ask the tool for a new one.", retryable=True)
    os.replace(tmp, dest)
    return _out({"status": "ok", "saved": str(dest), "bytes": written})


def main() -> int:
    p = argparse.ArgumentParser(description="Use Vitra through its server tools.")
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("tools", "describe", "call"):
        sp = sub.add_parser(name)
        sp.add_argument("--toolsets", help="opt-in toolsets to include, comma-separated")
        if name == "tools":
            sp.add_argument("--find", help="words the tool must mention")
        else:
            sp.add_argument("tool")
        if name == "call":
            sp.add_argument("args", nargs="?", help="JSON object of arguments, or - for stdin")
            sp.add_argument("--intent", help="briefly, what the user wants")
    up = sub.add_parser("upload")
    up.add_argument("path")
    dl = sub.add_parser("download")
    dl.add_argument("url")
    dl.add_argument("--to", required=True, help="file or folder to save into")
    dl.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    return {"tools": cmd_tools, "describe": cmd_describe, "call": cmd_call,
            "upload": cmd_upload, "download": cmd_download}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
