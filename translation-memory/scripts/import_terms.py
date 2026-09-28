#!/usr/bin/env python3
"""Load existing translations into a memory from a TMX, XLIFF, XLSX, CSV or
TSV file, so they're reused from now on.

  POST /v1/translation-memory/{id}/terms/import-file         multipart `file`
  GET  /v1/translation-memory/{id}/terms/import/{operation}  until done

Prints JSON: { "status": "imported" | "failed", "memory", "imported", "failed",
               "warnings" }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _tm  # noqa: E402

TM = "/v1/translation-memory"
KINDS = {".tmx", ".xlf", ".xliff", ".xlsx", ".csv", ".tsv"}
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Import translations into a memory.")
    parser.add_argument("--tm-name", required=True)
    parser.add_argument("--file", required=True, help="A .tmx .xliff .xlsx .csv or .tsv file.")
    parser.add_argument("--status", choices=["unverified", "verified", "approved"],
                        help="Trust level for entries the file doesn't mark (default: unverified).")
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()
    path = Path(args.file).expanduser()
    if not path.is_file():
        die(_common.EXIT_DOWNLOAD, f"--file not found: {path}")
    if path.suffix.lower() not in KINDS:
        die(_common.EXIT_API_ERROR, f"import takes {', '.join(sorted(KINDS))} files.")
    base, headers = _common.base_url(), _common.headers()
    tm = _tm.resolve(base, headers, args.tm_name)
    tm_path = f"{base}{TM}/{quote(str(tm['id']))}"
    try:
        status, payload = _http.post_multipart_json(f"{tm_path}/terms/import-file", headers, "file", path,
                                                    {"defaultStatus": args.status} if args.status else None)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error importing: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "import into memories"))
    if status not in (200, 201) or not isinstance(payload, dict) or not payload.get("operationId"):
        die(_common.EXIT_API_ERROR, f"the import did not start ({status}): {_common.api_message(payload)}")
    op, warnings = payload["operationId"], payload.get("warnings") or []
    sys.stderr.write(f"[import] {payload.get('total')} entr(ies) found\n")
    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=3)
    while True:
        status, row = _http.get_json(f"{tm_path}/terms/import/{quote(str(op))}", headers=headers)
        state = str((row or {}).get("status") or "").lower() if isinstance(row, dict) else ""
        if state in ("ready", "failed"):
            break
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "still importing; it continues on its own — check the memory later.")
        time.sleep(next(delays))
    print(json.dumps({"status": "imported" if state == "ready" else "failed", "memory": tm.get("name"),
                      "imported": row.get("imported"), "failed": row.get("failed"),
                      **({"error": row.get("error")} if row.get("error") else {}),
                      **({"warnings": warnings[:10]} if warnings else {})}, ensure_ascii=False))
    return _common.EXIT_OK if state == "ready" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
