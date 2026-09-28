#!/usr/bin/env python3
"""Translate a whole Drive folder: every supported file in it (and, if asked,
its subfolders) into up to 10 languages; the translations go into a new Drive
folder beside it.

Without --confirm it only PREVIEWS: which files would be translated, which
are skipped and why, and where the results would go. Nothing is charged.

  POST .../document/translate/folder/preview   (default)
  POST .../document/translate/folder           (--confirm)
  GET  .../document/batches/{id}               until each language settles

Prints JSON:
  preview   { "status": "preview", "folder", "files": N, "skipped": [..],
              "output_folder", "unsupported_targets": [..], "next_action" }
  run       { "status": "translated" | "partial" | "failed", "output_folder",
              "languages": [{"language", "format", "status", "files", "failed"}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _doc  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402
import _tm  # noqa: E402

# The formats a folder run translates (the API's FOLDER_RUN_FORMATS).
FORMATS = ["TEXT", "JSON", "XML", "HTML", "XLIFF", "DOCX", "PPTX", "XLSX", "CSV", "PDF"]
die = _common.die


def folder_id(name: str) -> str:
    base, headers = _common.base_url(), _common.headers()
    q = urlencode({"keyword": name, "searchScope": "global", "limit": 50})
    status, payload = _http.get_json(f"{base}/v1/assets-management?{q}", headers=headers)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read the Drive"))
    hits = [r for r in _tm.rows_of(payload) if isinstance(r, dict) and r.get("type") == "folder"
            and (r.get("name") or "").casefold() == name.casefold()]
    if len(hits) != 1:
        die(_common.EXIT_API_ERROR, f'{"no" if not hits else "more than one"} Drive folder is called "{name}".',
            error_code="FOLDER_UNKNOWN")
    return str(hits[0]["id"])


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate a Drive folder.")
    parser.add_argument("--folder", required=True, help="The Drive folder's name.")
    parser.add_argument("--target-language", action="append", required=True, metavar="LANGUAGE")
    parser.add_argument("--format", action="append", choices=FORMATS,
                        help="Only these kinds of file (default: every kind it supports).")
    parser.add_argument("--tm-name")
    parser.add_argument("--include-subfolders", action="store_true")
    parser.add_argument("--exclude", action="append", help="Skip paths containing this text (repeatable).")
    parser.add_argument("--layout", choices=["language-folder", "language-suffix"],
                        help="A folder per language (default), or one folder with a language suffix per file.")
    parser.add_argument("--confirm", action="store_true", help="Start it (after the user saw the preview).")
    parser.add_argument("--max-wait", type=int, default=7200)
    args = parser.parse_args()
    if len(args.target_language) > 10:
        die(_common.EXIT_API_ERROR, "at most 10 languages per folder run.")

    base, headers = _common.base_url(), _common.headers()
    tm = _tm.choose(base, headers, args.target_language[0], args.tm_name)
    body = {"folderId": folder_id(args.folder), "formats": args.format or FORMATS,
            "sourceLanguage": tm.get("sourceLanguage"),
            "targetLanguages": [_tm.target_in(tm, t, base, headers) for t in args.target_language],
            "tmId": str(tm["id"]), "suite": "OFFICE",
            **({"includeSubfolders": True} if args.include_subfolders else {}),
            **({"exclude": args.exclude} if args.exclude else {}),
            **({"layout": args.layout} if args.layout else {})}

    if not args.confirm:
        p = _doc.call("POST", "/translate/folder/preview", body, what="preview the folder")
        p = p.get("data") if isinstance(p, dict) and isinstance(p.get("data"), dict) else p
        files = p.get("files") or []
        print(json.dumps({"status": "preview", "folder": (p.get("folder") or {}).get("name"),
                          "files": len(files), "sample": [f.get("path") for f in files[:10]],
                          "skipped": (p.get("skipped") or [])[:10], "output_folder": p.get("outputFolderName"),
                          "unsupported_targets": p.get("unsupportedTargets") or [], "memory": tm.get("name"),
                          "next_action": "translate_folder --confirm"}, ensure_ascii=False))
        return 0

    key = _common.idempotency_key("doc-folder", body)
    known = _state.recall("document-translation", key)
    if known:
        run = known
        sys.stderr.write("[folder] reconnecting to the run already started\n")
    else:
        started = _doc.call("POST", "/translate/folder", body, what="translate the folder")
        started = started.get("data") if isinstance(started, dict) and isinstance(started.get("data"), dict) \
            else started
        run = {"output": (started.get("outputFolder") or {}).get("name"), "batches": started.get("batches") or []}
        _state.remember("document-translation", key, run)

    deadline = time.monotonic() + args.max_wait
    out = []
    for b in run["batches"]:
        delays = _http.poll_delays(first=10)
        while True:
            row = _doc.call("GET", f"/batches/{quote(str(b.get('batchId')))}", what="read the run")
            row = row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else row
            if str(row.get("status")).lower() in ("done", "partial", "failed"):
                break
            if time.monotonic() >= deadline:
                die(_common.EXIT_TIMEOUT, "still translating; it continues on its own. Run the same command "
                    "again to keep waiting.")
            time.sleep(next(delays))
        files = row.get("files") or []
        out.append({"language": b.get("targetLanguage"), "format": b.get("format"), "status": row.get("status"),
                    "files": sum(1 for f in files if str(f.get("status")).upper() == "DONE"),
                    "failed": [f.get("name") for f in files if str(f.get("status")).upper() == "FAILED"]})
    bad = sum(1 for o in out if o["status"] != "done")
    status = "translated" if not bad else ("failed" if bad == len(out) else "partial")
    print(json.dumps({"status": status, "output_folder": run.get("output"), "languages": out},
                     ensure_ascii=False))
    return _common.EXIT_OK if status == "translated" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
