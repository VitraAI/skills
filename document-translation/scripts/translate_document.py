#!/usr/bin/env python3
"""Translate a document or text into one or more languages, keeping its format.

Word, PowerPoint, Excel, CSV, PDF, HTML, JSON, XML, XLIFF, plain text files
(.txt), or text given directly. Every translation runs through a translation
memory; the source language is the memory's. One job per target language;
each translated file is saved next to the others in --out-dir.

  POST /v1/galaxy/playground/document/translate      (multipart file, or text)
       big Office files: POST /v1/assets-management/multi-upload first
  GET  /v1/galaxy/playground/document/logs/{id}      until DONE / FAILED
  GET  .../logs/{id}/export                          the translated file
  GET  .../logs/{id}/text-result                     the translated text

Re-running the same command reconnects to the jobs it started (nothing is
translated or charged twice).

Prints JSON:
  { "status": "translated" | "partial" | "failed", "memory",
    "results": [{"language", "path" | "text", "status", "translation"}], "next_action" }
`translation` identifies each result for proofread.py, back_translate.py and
quality_report.py (keep it; don't show it).

Stops with a question (`error.ask`) when the memory is the user's choice:
TM_CHOICE_NEEDED (with `choices`), TM_NEEDED.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
import time
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402
import _tm  # noqa: E402

DOC = "/v1/galaxy/playground/document"
DRIVE_UPLOAD = "/v1/assets-management/multi-upload"
DRIVE_LIST = "/v1/assets-management"
FORMATS = {".docx": "DOCX", ".pptx": "PPTX", ".xlsx": "XLSX", ".csv": "CSV", ".pdf": "PDF",
           ".html": "HTML", ".htm": "HTML", ".json": "JSON", ".xml": "XML",
           ".xlf": "XLIFF", ".xliff": "XLIFF", ".txt": "TEXT"}
OFFICE = {"DOCX", "PPTX", "XLSX"}
MAX_UPLOAD = 25 * 1024 * 1024  # the route's multipart cap
MAX_TEXT = 50_000
DEFAULT_MAX_WAIT = 1800
die = _common.die


def post_translate(base: str, headers: dict, fields: dict, file: Path | None) -> str:
    try:
        if file is not None:
            status, payload = _http.post_multipart_json(
                base + DOC + "/translate", headers, "file", file,
                {k: v for k, v in fields.items() if v is not None})
        else:
            status, payload = _http.post_json(base + DOC + "/translate", headers, fields)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the translation: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "translate documents"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"the translation did not start ({status}): {_common.api_message(payload)}")
    row = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    job = (row or {}).get("id") if isinstance(row, dict) else None
    if not job:
        die(_common.EXIT_API_ERROR, "Vitra did not return a translation job.")
    return str(job)


def drive_asset(base: str, headers: dict, path: Path) -> str:
    """Put a big Office file in the Drive (through the API) and return its id."""
    try:
        status, payload = _http.post_multipart_json(base + DRIVE_UPLOAD, headers, "files", path)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error uploading: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "upload files to the Drive"))
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
    key = next((r.get("key") for r in rows if isinstance(r, dict) and r.get("key") and not r.get("error")), None)
    if status not in (200, 201) or not key:
        die(_common.EXIT_API_ERROR, f"the upload failed ({status}): {_common.api_message(payload)}")
    # The upload answers with the storage key; the translation takes the asset id.
    query = urlencode({"keyword": path.name, "searchScope": "global", "limit": 20})
    status, payload = _http.get_json(f"{base}{DRIVE_LIST}?{query}", headers=headers)
    for row in _tm.rows_of(payload) if status == 200 else []:
        if isinstance(row, dict) and row.get("key") == key and row.get("id"):
            return str(row["id"])
    die(_common.EXIT_API_ERROR, "the file was uploaded but could not be found in the Drive yet; run again.",
        retryable=True)
    return ""  # unreachable


def read_log(base: str, headers: dict, job: str) -> dict:
    try:
        status, payload = _http.get_json(f"{base}{DOC}/logs/{quote(job)}", headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the translation: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read translations"))
    data = (payload or {}).get("data") if isinstance(payload, dict) else None
    if status != 200 or not isinstance(data, dict):
        die(_common.EXIT_API_ERROR, f"could not read the translation ({status}): {_common.api_message(payload)}")
    return data


def wait(base: str, headers: dict, job: str, label: str, deadline: float) -> dict:
    delays = _http.poll_delays(first=5)
    last = None
    while True:
        row = read_log(base, headers, job)
        state = str(row.get("status") or "").upper()
        if state != last:
            sys.stderr.write(f"[{label}] {state.lower() or 'queued'}\n")
            last = state
        if state in ("DONE", "FAILED"):
            return row
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, f"{label} is still translating. Run the same command again to keep "
                "waiting; it will not start a second translation.")
        time.sleep(next(delays))


def fetch_result(base: str, headers: dict, job: str, fmt: str, out: Path) -> dict:
    if fmt == "TEXT":
        status, payload = _http.get_json(f"{base}{DOC}/logs/{quote(job)}/text-result", headers=headers)
        text = ((payload or {}).get("data") or {}).get("translation") if isinstance(payload, dict) else None
        if status != 200 or not isinstance(text, str):
            die(_common.EXIT_API_ERROR, f"could not read the translated text ({status}).")
        if out.suffix:  # a .txt file in → a .txt file out
            out.write_text(text, encoding="utf-8")
            return {"path": str(out)}
        return {"text": text}
    try:
        _http.download_to_file(f"{base}{DOC}/logs/{quote(job)}/export?side=target", out, headers=headers,
                               timeout=600)
    except (_http.NetworkError, ValueError) as e:
        die(_common.EXIT_API_ERROR, f"could not download the translated file: {e}", retryable=True)
    return {"path": str(out)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate a document or text, keeping its format.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="The document (.docx .pptx .xlsx .csv .pdf .html .json .xml .xliff .txt).")
    src.add_argument("--text", help=f"Text to translate (up to {MAX_TEXT} characters).")
    parser.add_argument("--target-language", action="append", required=True, metavar="LANGUAGE",
                        help="Language to translate into (repeatable), e.g. French or fr-FR.")
    parser.add_argument("--tm-name", help="Translation memory, by the name list_tms.py shows.")
    parser.add_argument("--out-dir", default="translated", help="Where translated files go (default ./translated).")
    parser.add_argument("--columns", help="CSV only: which columns to translate, 0-based, e.g. 1,3.")
    parser.add_argument("--keep-first-row", action="store_true",
                        help="XLSX only: leave each sheet's first row (headings) untranslated.")
    parser.add_argument("--name", help="Name shown in Vitra. Defaults to the file name.")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    path = Path(args.file).expanduser() if args.file else None
    if path and not path.is_file():
        die(_common.EXIT_DOWNLOAD, f"--file not found: {path}")
    fmt = FORMATS.get(path.suffix.lower()) if path else "TEXT"
    if not fmt:
        die(_common.EXIT_API_ERROR, f"{path.suffix or 'that file type'} can't be translated here. Supported: "
            + ", ".join(sorted(FORMATS)))
    text = args.text if args.text is not None else (path.read_text(encoding="utf-8") if fmt == "TEXT" else None)
    if text is not None and len(text) > MAX_TEXT:
        die(_common.EXIT_API_ERROR, f"that text is over {MAX_TEXT} characters; save it as a .docx and translate the file.")
    size = path.stat().st_size if path else 0
    if fmt not in OFFICE and fmt != "TEXT" and size > MAX_UPLOAD:
        die(_common.EXIT_API_ERROR, f"{fmt} files are limited to 25 MB here.")

    targets = list(dict.fromkeys(args.target_language))
    tm = _tm.choose(base, headers, targets[0], args.tm_name)
    source = tm.get("sourceLanguage")
    spelled = [_tm.target_in(tm, t, base, headers) for t in targets]
    content_id = _common.sha256_file(path) if path else _common.idempotency_key("text", text)
    out_dir = Path(args.out_dir).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    name = args.name or (path.name if path else "Text")
    asset_id = None

    # Start (or reconnect to) one job per language, then wait for them all.
    jobs: list[tuple[str, str, str]] = []
    for target in spelled:
        key = _common.idempotency_key("doc", content_id, fmt, target, tm.get("id"), args.columns,
                                      args.keep_first_row)
        known = _state.recall("document-translation", key)
        if known and known.get("job"):
            sys.stderr.write(f"[{target}] reconnecting to the translation already started\n")
            jobs.append((target, known["job"], key))
            continue
        fields = {"format": fmt, "sourceLanguage": source, "targetLanguage": target, "suite": "OFFICE",
                  "tmId": str(tm.get("id")), "name": name}
        if fmt == "XLSX" and args.keep_first_row:
            fields["translateFirstRow"] = "false"
        if fmt == "CSV" and args.columns:
            fields["translateColumns"] = args.columns
        if fmt == "TEXT":
            job = post_translate(base, headers, {**fields, "sourceText": text}, None)
        elif fmt in OFFICE and size > MAX_UPLOAD:
            asset_id = asset_id or drive_asset(base, headers, path)
            job = post_translate(base, headers, {**fields, "assetId": asset_id}, None)
        else:
            job = post_translate(base, headers, fields, path)
        _state.remember("document-translation", key, {"job": job})
        jobs.append((target, job, key))

    deadline = time.monotonic() + args.max_wait
    results, failed = [], 0
    for target, job, key in jobs:
        row = wait(base, headers, job, target, deadline)
        if str(row.get("status")).upper() == "FAILED":
            _state.forget("document-translation", key)  # a re-run starts it afresh
            failed += 1
            results.append({"language": target, "status": "failed",
                            "error": row.get("error") or row.get("errorMessage") or "the translation failed"})
            continue
        stem = path.stem if path else "translation"
        suffix = path.suffix if path else ""
        out = out_dir / f"{stem}.{re.sub(r'[^A-Za-z0-9_-]+', '_', target)}{suffix}"
        results.append({"language": target, "status": "translated", "translation": job,
                         **fetch_result(base, headers, job, fmt, out)})

    status = "translated" if not failed else ("partial" if failed < len(jobs) else "failed")
    print(json.dumps({"status": status, "memory": tm.get("name"), "results": results,
                      "next_action": None if not failed else "translate_document"}, ensure_ascii=False))
    return _common.EXIT_OK if status == "translated" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
