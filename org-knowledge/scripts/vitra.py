#!/usr/bin/env python3
"""Use Vitra from any agent: every Vitra feature is a server tool, and this
script only forwards to it. The server does the work, the lookups by name,
the rules and the wording; nothing about Vitra lives here.

  vitra.py tools [--find WORDS]          the tools you may use (name, title)
  vitra.py describe TOOL                 what TOOL does and the arguments it takes
  vitra.py call TOOL [ARGS_JSON | - | --args-file FILE] [--intent TEXT] [--toolsets a,b]
                                         run TOOL with a JSON object of arguments
  vitra.py upload PATH                   put a local file in Vitra; prints its asset
                                         (and duration_seconds for MP4/MOV/M4A/M4V/MP3/WAV)
  vitra.py upload https://LINK [--name NAME]
                                         Vitra downloads the file at a public link itself
                                         (no local copy); prints its asset
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
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

TOOLS_PATH = "/v1/agent/tools"
MAX_ARGS_BYTES = 256 * 1024


# Where the published skills live; each skill has skills/<name>.json there.
CATALOG_VAR = "VITRA_SKILLS_CATALOG_URL"
DEFAULT_CATALOG = "https://vitraai.github.io/skills"
UPDATE_CHECK_SECONDS = 24 * 3600


def _local_hash(skill_dir: Path) -> str:
    """This copy's fingerprint, computed like scripts/build.mjs contentHash."""
    import hashlib

    paths = ["SKILL.md"] + sorted(f"scripts/{p.name}" for p in (skill_dir / "scripts").glob("*.py"))
    lines = ""
    for rel in sorted(paths):
        f = skill_dir / rel
        if f.is_file():
            lines += f"{rel}\0{hashlib.sha256(f.read_bytes()).hexdigest()}\n"
    return hashlib.sha256(lines.encode()).hexdigest()


def _in_git_checkout(path: Path) -> bool:
    """A developer's own repo: never overwrite unpublished work."""
    return any((p / ".git").exists() for p in [path, *path.parents])


def _updater(skill_dir: Path) -> list[str] | None:
    """The command that refreshes this install, or None if there is none here."""
    import shutil

    if "/.claude/plugins/" in skill_dir.as_posix():
        claude = shutil.which("claude")
        if claude:
            return ["sh", "-c", f'"{claude}" plugin marketplace update vitra && '
                                f'"{claude}" plugin update vitra@vitra']
        return None
    npx = shutil.which("npx")
    return [npx, "-y", "skills", "update", "-g", "-y"] if npx else None


def _update_notice() -> dict | None:
    """At most once a day per skill: if a newer version is published, update in
    the background (it takes effect on the next run).

    Silent when the catalog can't be reached (offline, sandboxed), when no
    updater is installed, in a git checkout, or with VITRA_SKILLS_NO_UPDATE_CHECK=1.
    """
    import subprocess
    import time

    if os.environ.get("VITRA_SKILLS_NO_UPDATE_CHECK") == "1":
        return None
    skill_dir = Path(__file__).resolve().parent.parent
    if _in_git_checkout(skill_dir):
        return None
    name = skill_dir.name
    stamp = _common.signin_file().with_name("skills-update-check.json")
    try:
        seen = json.loads(stamp.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        seen = {}
    seen = seen if isinstance(seen, dict) else {}
    last = seen.get(name)
    if isinstance(last, dict) and time.time() - float(last.get("at", 0)) < UPDATE_CHECK_SECONDS:
        return None
    notice = None
    try:
        base = (os.environ.get(CATALOG_VAR) or DEFAULT_CATALOG).rstrip("/")
        with urllib.request.urlopen(f"{base}/skills/{name}.json", timeout=3) as res:
            published = json.loads(res.read().decode("utf-8")).get("contentHash")
    except Exception:  # noqa: BLE001 — offline or blocked: try again later
        return None
    if isinstance(published, str) and published and published != _local_hash(skill_dir):
        command = _updater(skill_dir)
        if command:
            log = _common.signin_file().with_name("skills-update.log")
            try:
                with open(log, "ab") as out:
                    popen: dict = {"stdout": out, "stderr": out, "stdin": subprocess.DEVNULL}
                    if os.name == "nt":
                        popen["creationflags"] = 0x00000008 | 0x00000200
                    else:
                        popen["start_new_session"] = True
                    subprocess.Popen(command, **popen)
                notice = {"updating": True,
                          "note": "A newer version of the Vitra skills is installing in the "
                                  "background; it takes effect the next time a skill runs."}
            except OSError:
                notice = None
    try:
        seen[name] = {"at": time.time()}
        _common.write_private(stamp, seen)
    except OSError:
        pass
    return notice


def _out(obj: object) -> int:
    if isinstance(obj, dict) and obj.get("status") == "ok":
        notice = _update_notice()
        if notice:
            obj["skills_update"] = notice
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
        if _common.credential() == "signin":
            # The sign-in ended or was revoked: forget it and hand out a new link.
            _common.write_signin(None)
            _common._missing()
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
    raw = a.args
    if a.args_file:
        if a.args is not None:
            _common.die(_common.EXIT_API_ERROR, "Pass the arguments once: as ARGS_JSON or --args-file, not both.",
                        error_code="BAD_ARGUMENTS", retryable=False)
        try:
            raw = Path(a.args_file).expanduser().read_text(encoding="utf-8-sig")
        except OSError as e:
            _common.die(_common.EXIT_API_ERROR, f"Can't read --args-file {a.args_file} ({e.strerror}).",
                        error_code="BAD_ARGUMENTS", retryable=False)
    body: dict = {"args": _parse_args(raw)}
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


_TIMED = {".mp4", ".mov", ".m4a", ".m4v"}
_WAV = {".wav", ".wave"}
_MP3 = {".mp3"}


def _box_header(fh, end: int) -> tuple[bytes, int, int] | None:
    """(type, payload start, box end) of the MP4 box at the file position,
    or None when there is no whole header before `end`."""
    start = fh.tell()
    head = fh.read(8)
    if len(head) < 8:
        return None
    size, kind = int.from_bytes(head[:4], "big"), head[4:]
    if size == 1:  # 64-bit size follows
        big = fh.read(8)
        if len(big) < 8:
            return None
        size = int.from_bytes(big, "big")
    elif size == 0:  # runs to the end of its parent
        size = end - start
    body = fh.tell()
    if size < body - start or start + size > end:
        return None
    return kind, body, start + size


def _media_seconds(path: Path) -> float | None:
    """The length of an audio or video file, read from its headers only, or
    None when it can't be told."""
    suffix = path.suffix.lower()
    try:
        if suffix in _TIMED:
            return _mp4_seconds(path)
        if suffix in _WAV:
            return _wav_seconds(path)
        if suffix in _MP3:
            return _mp3_seconds(path)
    except (OSError, ValueError):
        return None
    return None


def _wav_seconds(path: Path) -> float | None:
    """A WAV file's length: its data chunk size over the fmt byte rate."""
    with path.open("rb") as fh:
        head = fh.read(12)
        if len(head) < 12 or head[:4] != b"RIFF" or head[8:12] != b"WAVE":
            return None
        rate = None
        for _ in range(1000):
            chunk = fh.read(8)
            if len(chunk) < 8:
                return None
            kind, size = chunk[:4], int.from_bytes(chunk[4:8], "little")
            if kind == b"fmt ":
                fmt = fh.read(size)
                if len(fmt) < 12:
                    return None
                rate = int.from_bytes(fmt[8:12], "little")  # bytes per second
                if size % 2:
                    fh.seek(1, 1)
                continue
            if kind == b"data":
                if not rate:
                    return None
                if size in (0, 0xFFFFFFFF):  # streamed: size unknown, use the file
                    size = path.stat().st_size - fh.tell()
                return round(size / rate, 3) if size > 0 else None
            fh.seek(size + (size % 2), 1)
    return None


_MP3_BITRATES = {  # kbps by (MPEG-1?, layer III) index
    True: [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320],
    False: [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160],
}
_MP3_RATES = {3: [44100, 48000, 32000], 2: [22050, 24000, 16000], 0: [11025, 12000, 8000]}


def _mp3_seconds(path: Path) -> float | None:
    """An MP3's length: the Xing/Info or VBRI frame count when the file has one
    (variable bit rate), else the first frame's bit rate over the audio size."""
    size = path.stat().st_size
    with path.open("rb") as fh:
        head = fh.read(10)
        start = 0
        if head[:3] == b"ID3" and len(head) == 10:  # skip the ID3v2 tag
            start = 10 + ((head[6] & 0x7F) << 21 | (head[7] & 0x7F) << 14
                          | (head[8] & 0x7F) << 7 | (head[9] & 0x7F))
        fh.seek(start)
        buf = fh.read(65536)
    for i in range(len(buf) - 4):
        if buf[i] != 0xFF or (buf[i + 1] & 0xE0) != 0xE0:
            continue
        version = (buf[i + 1] >> 3) & 3  # 3 = MPEG-1, 2 = MPEG-2, 0 = MPEG-2.5
        layer = (buf[i + 1] >> 1) & 3  # 1 = layer III
        bitrate_ix, rate_ix = buf[i + 2] >> 4, (buf[i + 2] >> 2) & 3
        if version == 1 or layer != 1 or bitrate_ix in (0, 15) or rate_ix == 3:
            continue
        mpeg1 = version == 3
        rate = _MP3_RATES[version][rate_ix]
        per_frame = 1152 if mpeg1 else 576
        mono = (buf[i + 3] >> 6) == 3
        side = (17 if mono else 32) if mpeg1 else (9 if mono else 17)
        xing = buf[i + 4 + side:i + 4 + side + 12]
        if xing[:4] in (b"Xing", b"Info") and int.from_bytes(xing[4:8], "big") & 1:
            frames = int.from_bytes(xing[8:12], "big")
            return round(frames * per_frame / rate, 3) if frames else None
        vbri = buf[i + 36:i + 36 + 18]
        if vbri[:4] == b"VBRI":
            frames = int.from_bytes(vbri[14:18], "big")
            return round(frames * per_frame / rate, 3) if frames else None
        kbps = _MP3_BITRATES[mpeg1][bitrate_ix]
        audio = size - start - i
        if size >= 128:
            with path.open("rb") as fh:
                fh.seek(size - 128)
                if fh.read(3) == b"TAG":  # ID3v1 tag at the end
                    audio -= 128
        return round(audio * 8 / (kbps * 1000), 3) if audio > 0 else None
    return None


def _mp4_seconds(path: Path) -> float | None:
    """The length an MP4 / MOV / M4A / M4V file declares (moov -> mvhd), read
    from box headers only (a few hundred bytes), or None when it can't be."""
    try:
        with path.open("rb") as fh:
            end = path.stat().st_size
            for _ in range(2):  # the file, then moov
                for _ in range(1000):
                    box = _box_header(fh, end)
                    if box is None:
                        return None
                    kind, body, box_end = box
                    if kind in (b"moov", b"mvhd"):
                        break
                    fh.seek(box_end)
                else:
                    return None
                if kind == b"mvhd":
                    break
                end = box_end  # search inside moov
            if kind != b"mvhd":
                return None
            data = fh.read(min(box_end - body, 32))
            if len(data) < 20:
                return None
            if data[0] == 1:  # version 1: 64-bit times
                if len(data) < 32:
                    return None
                scale = int.from_bytes(data[20:24], "big")
                length = int.from_bytes(data[24:32], "big")
                unknown = 0xFFFFFFFFFFFFFFFF
            else:
                scale = int.from_bytes(data[12:16], "big")
                length = int.from_bytes(data[16:20], "big")
                unknown = 0xFFFFFFFF
    except OSError:
        return None
    if not scale or not length or length == unknown:
        return None
    return round(length / scale, 3)


def cmd_import(link: str, name: str | None) -> int:
    """A file at a public link: the server downloads it (import_file), so the
    bytes never pass through this machine."""
    if urllib.parse.urlsplit(link).scheme != "https":
        _common.die(_common.EXIT_DOWNLOAD, "Only public https:// links can be imported.",
                    retryable=False)
    args: dict = {"url": link}
    if name:
        args["file_name"] = name
    asset = _call_tool("import_file", args)
    return _out({"status": "ok", "asset": asset,
                 "next_action": "Pass asset.asset_id to the tool that needs the file."})


def cmd_upload(a: argparse.Namespace) -> int:
    if a.path.lower().startswith(("https://", "http://")):
        return cmd_import(a.path, a.name)
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
    # `key` is the storage key: the tools that take an `asset_key` (image
    # translation, image resize) need it rather than the asset_id.
    seconds = _media_seconds(path)
    return _out({"status": "ok", "file": path.name, "bytes": size, "asset": asset,
                 "key": key,
                 # The audio or video length, for the tools that take duration_seconds.
                 **({"duration_seconds": seconds} if seconds else {}),
                 "next_action": "Pass asset.asset_id (or key, where a tool asks for "
                                "asset_key) to the tool that needs the file."})


def _link_file_name(url: urllib.parse.SplitResult) -> str:
    """The file name a download link carries: the one a presigned link asks
    the browser to save as, else the last part of its path. Never a path."""
    query = urllib.parse.parse_qs(url.query)
    for disposition in query.get("response-content-disposition", []):
        m = re.search(r"filename\*?=(?:UTF-8'')?\"?([^\";]+)", disposition)
        if m:
            name = Path(urllib.parse.unquote(m.group(1))).name
            if name:
                return name
    return Path(urllib.parse.unquote(url.path)).name or "download"


def cmd_download(a: argparse.Namespace) -> int:
    url = urllib.parse.urlsplit(a.url)
    if url.scheme != "https" or not url.hostname:
        _common.die(_common.EXIT_DOWNLOAD,
                    "Only https links can be downloaded; Vitra's download links always are.",
                    retryable=False)
    dest = Path(a.to).expanduser()
    # `--to downloads/` names a folder even before it exists.
    if a.to.endswith(("/", os.sep)) or dest.is_dir():
        dest.mkdir(parents=True, exist_ok=True)
        dest = dest / _link_file_name(url)
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
            sp.add_argument("--args-file", help="read the JSON arguments from this file "
                            "(any shell: no quoting of apostrophes or quotes)")
            sp.add_argument("--intent", help="briefly, what the user wants")
    up = sub.add_parser("upload")
    up.add_argument("path", help="a local file, or a public https:// link")
    up.add_argument("--name", help="Drive name for a file imported from a link")
    dl = sub.add_parser("download")
    dl.add_argument("url")
    dl.add_argument("--to", required=True, help="file or folder to save into")
    dl.add_argument("--overwrite", action="store_true")
    a = p.parse_args()
    return {"tools": cmd_tools, "describe": cmd_describe, "call": cmd_call,
            "upload": cmd_upload, "download": cmd_download}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
