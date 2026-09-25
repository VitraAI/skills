#!/usr/bin/env python3
"""Set how a phrase is translated in a memory the whole organization reuses.

  GET /v1/translation-memory/{id}/terms?search=   the current wording (before)
  PUT /v1/translation-memory/{id}/terms           { sourceText, targetLanguage, targetText, status }

Only with wording the user gave or approved. Prints the change as
before → after:

  { "status": "saved", "memory", "source", "language", "before", "after", "review" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _tm  # noqa: E402
import search_terms  # noqa: E402

TM = "/v1/translation-memory"


def main() -> int:
    parser = argparse.ArgumentParser(description="Correct a translation memory entry.")
    parser.add_argument("--tm-name", required=True)
    parser.add_argument("--source-text", required=True)
    parser.add_argument("--target-language", required=True)
    parser.add_argument("--target-text", required=True, help="The correct translation.")
    parser.add_argument("--status", default="approved", choices=["unverified", "verified", "approved"],
                        help="How trusted the wording is (default approved: the user gave it).")
    args = parser.parse_args()
    base, headers = _common.base_url(), _common.headers()
    tm = _tm.resolve(base, headers, args.tm_name)
    language = _tm.target_in(tm, args.target_language, base, headers)
    current = next((e for e in search_terms.entries(base, headers, str(tm["id"]), search=args.source_text,
                                                     language=language, limit=50)
                    if e.get("source") == args.source_text and e.get("language") == language), {})
    body = {"sourceText": args.source_text, "targetLanguage": language, "targetText": args.target_text,
            "status": args.status,
            # Lets the server refuse if someone changed it since it was read.
            **({"previousTargetText": current["text"]} if current.get("text") else {})}
    try:
        status, payload = _http.put_json(f"{base}{TM}/{quote(str(tm['id']))}/terms", headers, body)
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error saving: {e}", retryable=True)
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "edit memories"))
    if status == 409:
        _common.die(_common.EXIT_API_ERROR, "someone changed this entry since it was read; nothing was saved. "
                    "Search again and redo it.", error_code="CONFLICT")
    if status not in (200, 201):
        _common.die(_common.EXIT_API_ERROR, f"could not save ({status}): {_common.api_message(payload)}")
    print(json.dumps({"status": "saved", "memory": tm.get("name"), "source": args.source_text,
                      "language": language, "before": current.get("text"), "after": args.target_text,
                      "review": args.status}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
