#!/usr/bin/env python3
"""Download one language's subtitles as a file.

Single source: `sync-lib.sh` copies this file into the subtitle skills. Edit it
here only, then run the sync.

  GET .../process-log/{id}/subtitle-download?language=&format=

Formats: srt (default), vtt, dfxp, xml, stl, edl, txt, txt-timed, json.

Prints JSON: { "status": "downloaded", "path", "format", "lines", "bytes" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

PATH = "/v1/galaxy/translate-video/process-log/{job_id}/subtitle-download"
# The formats the API offers.
FORMATS = ["srt", "vtt", "dfxp", "xml", "stl", "edl", "txt", "txt-timed", "json"]
die = _common.die


def download(base: str, headers: dict, job_id: str, language: str, fmt: str, out: Path) -> dict:
    """Write one language's subtitles to `out`; returns {path, format, lines, bytes}."""
    query = urlencode({"language": language, "format": fmt})
    try:
        status, payload = _http.get_json(f"{base}{PATH.format(job_id=job_id)}?{query}", headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error downloading subtitles: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "download subtitles"))
    if status != 200 or not isinstance(payload, dict):
        die(_common.EXIT_API_ERROR, f"could not download subtitles ({status}): {_common.api_message(payload)}")
    file = payload.get("file") if isinstance(payload.get("file"), dict) else {}
    content = file.get("content")
    lines = payload.get("subtitles") if isinstance(payload.get("subtitles"), list) else []
    if not isinstance(content, str) or not content.strip():
        die(_common.EXIT_API_ERROR, f"{language} has no subtitles to download yet.")
    out = out.expanduser()
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(content, encoding="utf-8")
    return {"path": str(out), "format": fmt, "lines": len(lines), "bytes": len(content.encode("utf-8"))}


def main() -> int:
    parser = argparse.ArgumentParser(description="Download subtitles as a file.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True)
    parser.add_argument("--format", default="srt", choices=FORMATS)
    parser.add_argument("--out", required=True, help="Where to write the file, e.g. ./hindi.srt")
    args = parser.parse_args()
    got = download(_common.base_url(), _common.headers(), args.job_id, args.language, args.format,
                   Path(args.out))
    print(json.dumps({"status": "downloaded", **got}))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
