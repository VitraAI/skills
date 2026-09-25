#!/usr/bin/env python3
"""Translate short texts through a translation memory: approved wording first,
machine translation for the rest, and every result stored back in the memory.

  POST /v1/translation-memory/translate          { tmId, sourceTexts, targetLanguages }
  GET  /v1/translation-memory/operations/{id}    for large batches

Texts: --text (repeatable), or --file with one text per line (UI strings,
product copy, short sentences). Languages as the memory lists them, or names.

Prints JSON: { "status": "translated", "memory", "translations":
               {"<language>": [{"source", "text", "match", "status"}]} }
`match` says where each came from: exact (the memory), fuzzy, mt (machine).

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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
MAX_TEXTS = 500
DEFAULT_MAX_WAIT = 900
die = _common.die


def groups_of(payload: object) -> list:
    body = payload if isinstance(payload, dict) else {}
    for key in ("data", "result"):
        if isinstance(body.get(key), list):
            return body[key]
        if isinstance(body.get(key), dict):
            inner = body[key]
            for k in ("data", "result"):
                if isinstance(inner.get(k), list):
                    return inner[k]
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate short texts through a translation memory.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", action="append", help="A text to translate (repeatable).")
    src.add_argument("--file", help="A text file, one text per line.")
    parser.add_argument("--target-language", action="append", required=True, metavar="LANGUAGE")
    parser.add_argument("--tm-name", help="The memory, by the name list_tms.py shows.")
    parser.add_argument("--instructions", help="Extra guidance, e.g. 'formal, for bank customers'.")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    texts = args.text or [ln.strip() for ln in Path(args.file).expanduser().read_text(encoding="utf-8").splitlines()
                          if ln.strip()]
    if not texts:
        die(_common.EXIT_API_ERROR, "there is no text to translate.")
    if len(texts) > MAX_TEXTS:
        die(_common.EXIT_API_ERROR, f"at most {MAX_TEXTS} texts at once; for documents use document-translation.")
    base, headers = _common.base_url(), _common.headers()
    tm = _tm.choose(base, headers, args.target_language[0], args.tm_name)
    targets = [_tm.target_in(tm, t, base, headers) for t in args.target_language]
    body = {"tmId": str(tm["id"]), "sourceTexts": texts, "targetLanguages": targets,
            **({"additionalPrompt": args.instructions} if args.instructions else {})}
    try:
        status, payload = _http.post_json(base + TM + "/translate", headers, body, timeout=300)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error translating: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "translate with memories"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not translate ({status}): {_common.api_message(payload)}")

    op = payload.get("operationId") if isinstance(payload, dict) else None
    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=5)
    while op:  # a large batch runs in the background
        sys.stderr.write("[memory] translating a large batch\n")
        time.sleep(next(delays))
        status, payload = _http.get_json(f"{base}{TM}/operations/{quote(str(op))}", headers=headers)
        state = str((payload or {}).get("status") or "").lower() if isinstance(payload, dict) else ""
        if status == 200 and state in ("ready", "completed", "done"):
            break
        if state == "failed":
            die(_common.EXIT_API_ERROR, f"the translation failed: {_common.api_message(payload)}")
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "the batch is still translating; try again in a few minutes.")

    out: dict[str, list] = {}
    for group in groups_of(payload):
        if not isinstance(group, dict):
            continue
        out[group.get("targetLanguage")] = [{k: v for k, v in {
            "source": t.get("sourceText"), "text": t.get("targetText"), "match": t.get("matchType"),
            "status": t.get("status")}.items() if v is not None}
            for t in group.get("translations") or [] if isinstance(t, dict)]
    print(json.dumps({"status": "translated", "memory": tm.get("name"), "translations": out}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
