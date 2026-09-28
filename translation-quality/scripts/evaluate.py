#!/usr/bin/env python3
"""Score a translation — accuracy, fluency, terminology and style — line by
line, against the organization's memory and terminology.

Input: --pairs FILE, either CSV/TSV with two columns (source, translation; a
header row is fine) or JSON [{"source": "…", "target": "…"}]; or two aligned
files, --source-file and --target-file, one line each.

  POST /v1/aiqe/reports            { memoryId, sourceLanguage, targetLanguage, segments }
  GET  /v1/aiqe/reports/{id}       until finished
  GET  /v1/aiqe/reports/{id}/segments

Prints JSON:
  { "status": "scored", "score", "band", "passed", "lines": N, "lines_with_errors": N,
    "worst": [{"line", "source", "translation", "score", "errors":
               [{"severity", "category", "why", "suggestion"}], "better"}],
    "memory", "next_action" }
`worst` lists the lines with errors, lowest score first (up to --show).

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import csv
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _aiqe  # noqa: E402
import _tm  # noqa: E402

AIQE = "/v1/aiqe/reports"
MAX_LINES = 2000
die = _common.die


def read_pairs(args) -> list[dict]:
    if args.source_file:
        src = Path(args.source_file).expanduser().read_text(encoding="utf-8").splitlines()
        tgt = Path(args.target_file).expanduser().read_text(encoding="utf-8").splitlines()
        if len(src) != len(tgt):
            die(_common.EXIT_API_ERROR, f"the files don't line up ({len(src)} vs {len(tgt)} lines).")
        return [{"source": s, "target": t} for s, t in zip(src, tgt) if s.strip() and t.strip()]
    path = Path(args.pairs).expanduser()
    if not path.is_file():
        die(_common.EXIT_DOWNLOAD, f"--pairs not found: {path}")
    if path.suffix.lower() == ".json":
        rows = json.loads(path.read_text(encoding="utf-8"))
        return [{"source": str(r.get("source")), "target": str(r.get("target"))}
                for r in rows if isinstance(r, dict) and r.get("source") and r.get("target")]
    dialect = "excel-tab" if path.suffix.lower() == ".tsv" else "excel"
    rows = [r for r in csv.reader(path.read_text(encoding="utf-8-sig").splitlines(), dialect=dialect) if len(r) >= 2]
    if rows and rows[0][0].strip().lower() in ("source", "src", "original"):
        rows = rows[1:]
    return [{"source": r[0], "target": r[1]} for r in rows if r[0].strip() and r[1].strip()]


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a translation line by line.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--pairs", help="CSV/TSV (source, translation) or JSON pairs.")
    src.add_argument("--source-file", help="Source lines; with --target-file.")
    parser.add_argument("--target-file")
    parser.add_argument("--source-language", required=True, help="e.g. en-US or English.")
    parser.add_argument("--target-language", required=True)
    parser.add_argument("--tm-name", help="The memory whose terminology applies (list_tms.py).")
    parser.add_argument("--domain", help="e.g. legal, marketing, UI.")
    parser.add_argument("--instructions", help="What else to judge, e.g. 'formal register'.")
    parser.add_argument("--title", help="A name for the report.")
    parser.add_argument("--show", type=int, default=10, help="How many of the worst lines to show.")
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()
    if args.source_file and not args.target_file:
        die(_common.EXIT_API_ERROR, "--source-file needs --target-file.")

    pairs = read_pairs(args)
    if not pairs:
        die(_common.EXIT_API_ERROR, "no source → translation pairs were found.")
    if len(pairs) > MAX_LINES:
        die(_common.EXIT_API_ERROR, f"at most {MAX_LINES} lines per report; split the file.")
    base, headers = _common.base_url(), _common.headers()
    tm = _tm.choose(base, headers, args.target_language, args.tm_name)
    body = {"memoryId": str(tm["id"]),
            "referenceId": _common.idempotency_key("aiqe", pairs, args.source_language, args.target_language),
            "referenceType": "skill",
            # The report takes BCP-47 codes (en-US), whatever the user or the memory calls them.
            "sourceLanguage": _tm.language_code(base, headers, args.source_language),
            "targetLanguage": _tm.language_code(base, headers, _tm.target_in(tm, args.target_language, base, headers)),
            "segments": [{"key": str(i), **p} for i, p in enumerate(pairs, 1)],
            **{k: v for k, v in {"title": args.title, "domain": args.domain,
                                 "additionalInstructions": args.instructions}.items() if v}}
    try:
        status, payload = _http.post_json(base + AIQE, headers, body, timeout=300)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the report: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "run quality reports"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    report = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    rid = (report or {}).get("id") if isinstance(report, dict) else None
    if status not in (200, 201) or not rid:
        die(_common.EXIT_API_ERROR, f"the report did not start ({status}): {_common.api_message(payload)}")

    report = _aiqe.wait(base, headers, report, args.max_wait)
    count, worst = _aiqe.worst_lines(base, headers, str(rid), args.show)
    print(json.dumps({"status": "scored", **_aiqe.summary(report), "lines": len(pairs),
                      "lines_with_errors": count if count else _aiqe.summary(report)["lines_with_errors"] or 0,
                      "worst": worst, "memory": tm.get("name"), "next_action": None}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
