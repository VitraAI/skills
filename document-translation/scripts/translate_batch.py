#!/usr/bin/env python3
"""Translate several files of one kind together (up to 20), into one or more
languages: one batch per language, every file saved per language.

  POST .../document/translate/batch    multipart `files` + format, languages, memory
  GET  .../document/batches/{id}       until done / partial / failed
  GET  .../document/logs/{file}/export each translated file

Re-running the same command reconnects to the batches it started.

Prints JSON: { "status": "translated" | "partial" | "failed", "memory",
               "languages": [{"language", "status", "files": [paths],
               "failed": [names]}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _doc  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402
import _tm  # noqa: E402
import translate_document  # noqa: E402

MAX_FILES = 20
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate several files together.")
    parser.add_argument("--file", action="append", required=True, help="A file (repeat; same kind, up to 20).")
    parser.add_argument("--target-language", action="append", required=True, metavar="LANGUAGE")
    parser.add_argument("--tm-name")
    parser.add_argument("--name", help="The batch's name in Vitra.")
    parser.add_argument("--out-dir", default="translated")
    parser.add_argument("--max-wait", type=int, default=3600)
    args = parser.parse_args()

    files = [Path(f).expanduser() for f in args.file]
    if len(files) > MAX_FILES:
        die(_common.EXIT_API_ERROR, f"at most {MAX_FILES} files per batch; for more, translate a Drive folder.")
    for f in files:
        if not f.is_file():
            die(_common.EXIT_DOWNLOAD, f"--file not found: {f}")
    kinds = {translate_document.FORMATS.get(f.suffix.lower()) for f in files}
    if None in kinds or len(kinds) != 1:
        die(_common.EXIT_API_ERROR, "a batch is one kind of file (all .docx, all .json, …); "
            "run one batch per kind.")
    fmt = kinds.pop()
    base, headers = _common.base_url(), _common.headers()
    tm = _tm.choose(base, headers, args.target_language[0], args.tm_name)
    targets = [_tm.target_in(tm, t, base, headers) for t in args.target_language]
    content = sorted(_common.sha256_file(f) for f in files)

    batches: list[tuple[str, str]] = []
    for target in targets:
        key = _common.idempotency_key("doc-batch", content, fmt, target, tm.get("id"))
        known = _state.recall("document-translation", key)
        if known:
            batches.append((target, known["batch"]))
            continue
        fields = {"format": fmt, "sourceLanguage": tm.get("sourceLanguage"), "targetLanguage": target,
                  "suite": "OFFICE", "tmId": str(tm["id"]), **({"name": args.name} if args.name else {})}
        try:
            status, payload = _http.post_multipart_files(base + _doc.DOC + "/translate/batch", headers,
                                                         [("files", f) for f in files], fields, timeout=1800)
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error starting the batch: {e}", retryable=True)
        if status in (401, 403):
            die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "translate documents"))
        if status == 402:
            die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
                error_code="INSUFFICIENT_CREDITS")
        row = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
        if status not in (200, 201) or not isinstance(row, dict) or not row.get("batchId"):
            die(_common.EXIT_API_ERROR, f"the batch did not start ({status}): {_common.api_message(payload)}")
        _state.remember("document-translation", key, {"batch": row["batchId"]})
        batches.append((target, row["batchId"]))

    deadline = time.monotonic() + args.max_wait
    out, failures = [], 0
    for target, bid in batches:
        delays = _http.poll_delays(first=5)
        while True:
            b = _doc.call("GET", f"/batches/{quote(bid)}", what="read the batch")
            b = b.get("data") if isinstance(b, dict) and isinstance(b.get("data"), dict) else b
            if str(b.get("status")).lower() in ("done", "partial", "failed"):
                break
            if time.monotonic() >= deadline:
                die(_common.EXIT_TIMEOUT, "still translating; run the same command again to keep waiting.")
            done = sum(1 for f in b.get("files") or [] if str(f.get("status")).upper() in ("DONE", "FAILED"))
            sys.stderr.write(f"[{target}] {done}/{b.get('fileCount')} files\n")
            time.sleep(next(delays))
        saved, failed = [], []
        for f in b.get("files") or []:
            if str(f.get("status")).upper() != "DONE":
                failed.append(f.get("name"))
                continue
            dest = Path(args.out_dir) / re.sub(r"[^A-Za-z0-9_-]+", "_", target) / str(f.get("name"))
            saved.append(_doc.download(str(f.get("id")), str(dest)))
        failures += len(failed)
        out.append({"language": target, "status": b.get("status"), "files": saved,
                    **({"failed": failed} if failed else {})})
    status = "translated" if not failures else ("failed" if not any(o["files"] for o in out) else "partial")
    print(json.dumps({"status": status, "memory": tm.get("name"), "languages": out}, ensure_ascii=False))
    return _common.EXIT_OK if status == "translated" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
