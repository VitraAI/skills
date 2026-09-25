#!/usr/bin/env python3
"""Find videos already uploaded to this organization — by content or by name —
and the dubs already made from them.

  GET /v1/galaxy/translate-video/upload?checksum=<sha256>   exact same bytes
  GET /v1/galaxy/translate-video/upload?keyword=<name>      name contains
  GET /v1/galaxy/translate-video/process-log?uploadId=<id>  dubs of that upload

`--file` hashes a local file first, so "have we uploaded this before?" is
answered by content, not by a name that may have changed. dub_video.py does the
same lookup on its own; this is for asking before starting, or for picking up
a dub from another machine.

Prints JSON:
  { "status": "ok", "assets": [{ upload_id, name, sha256, media_type, size_bytes,
      status, dubs: [{ job_id, status, source_language, target_languages }] }] }

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

UPLOAD_PATH = "/v1/galaxy/translate-video/upload"
LIST_PATH = "/v1/galaxy/translate-video/process-log"

die = _common.die


def get(base: str, headers: dict, path: str, query: dict, what: str) -> dict:
    try:
        status, payload = _http.get_json(f"{base}{path}?{urlencode(query)}", headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error {what}: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status != 200:
        die(_common.EXIT_API_ERROR, f"{what} failed ({status}): {_common.api_message(payload)}")
    return payload if isinstance(payload, dict) else {}


def dubs_of(base: str, headers: dict, upload_id: str) -> list[dict] | None:
    """Dubs made from this upload; None when the server cannot filter by upload.

    An older server ignores the filter and would list every dub, so an id that
    cannot match is tried first — a server that filters returns nothing for it.
    """
    import uuid

    probe = get(base, headers, LIST_PATH, {"uploadId": str(uuid.uuid4()), "limit": 1}, "listing dubs")
    if probe.get("data"):
        return None
    rows = get(base, headers, LIST_PATH, {"uploadId": upload_id, "limit": 20}, "listing dubs").get("data") or []
    return [
        {
            "job_id": r.get("id"),
            "name": r.get("processName"),
            "status": r.get("status"),
            "source_language": r.get("sourceLanguage"),
            "target_languages": r.get("targetLanguages"),
        }
        for r in rows
        if isinstance(r, dict)
    ]


def main() -> int:
    parser = argparse.ArgumentParser(description="Find uploaded videos and the dubs made from them.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--file", help="Local file: find uploads with exactly these bytes.")
    which.add_argument("--sha256", help="SHA-256 of the file.")
    which.add_argument("--name", help="Part of the file name.")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    if args.file:
        path = Path(args.file).expanduser()
        if not path.is_file():
            die(_common.EXIT_DOWNLOAD, f"no such file: {path}")
        sha = _common.sha256_file(path)
        query = {"checksum": sha, "limit": args.limit}
    elif args.sha256:
        sha = args.sha256.lower()
        query = {"checksum": sha, "limit": args.limit}
    else:
        sha = None
        query = {"keyword": args.name, "limit": args.limit, "mediaType": "video"}

    rows = get(base, headers, UPLOAD_PATH, query, "searching uploads").get("data") or []
    assets = []
    lookup_supported = True
    for row in rows:
        if not isinstance(row, dict):
            continue
        # An older server ignores ?checksum= and lists everything: keep only
        # real matches rather than trust the filter.
        if sha and row.get("sha256") != sha:
            continue
        dubs = dubs_of(base, headers, row["id"]) if lookup_supported else None
        if dubs is None:
            lookup_supported = False
        assets.append({
            "upload_id": row.get("id"),
            "name": row.get("originalName"),
            "sha256": row.get("sha256"),
            "media_type": row.get("mediaType"),
            "size_bytes": row.get("sizeBytes"),
            "status": row.get("status"),
            "dubs": dubs,
        })

    print(json.dumps({"status": "ok", "assets": assets,
                      "dub_lookup_supported": lookup_supported}))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
