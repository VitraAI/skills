#!/usr/bin/env python3
"""List the validation issues blocking export for one language.

  GET .../process-log/transcript/issues?id=<job>&lang=<language_key>
  -> { errors: [...], warnings: [...] }

ERRORS block export. `export_dub.py` refuses to render while any remain, which
is the whole point of separating review from export: a dub that exports with a
broken transcript wastes a render and ships a bad deliverable.

WARNINGS do not block. Report them and let the caller decide.

Prints JSON:
  { "status": "blocked" | "clean", "language": "...",
    "errors": [{"card_id": "...", "type": "...", "message": "...",
                "suggestion": "..."}],
    "warnings": [...], "next_action": "export_dub" }

Exit 0 either way — "there are errors" is a finding, not a failure. Read
`status` to decide, not the exit code.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
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

ISSUES_PATH = "/v1/galaxy/translate-video/process-log/transcript/issues"

die = _common.die


def normalize(raw: object) -> list[dict]:
    """Server issue -> a shape the agent can report without decoding internals.

    `transcript` on the server row carries the full card text; it is dropped
    here so a long transcript does not swamp the output.
    """
    rows = raw if isinstance(raw, list) else []
    out = []
    for item in rows:
        if not isinstance(item, dict):
            continue
        out.append(
            {
                "card_id": item.get("transcriptId"),
                "type": item.get("type"),
                "message": item.get("msg"),
                "suggestion": item.get("suggestion"),
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List validation issues blocking export for one language."
    )
    parser.add_argument("--job-id", required=True, help="The dub's job id.")
    parser.add_argument(
        "--language",
        required=True,
        help="Target language key, e.g. hindi_india (issues are per language).",
    )
    args = parser.parse_args()

    query = urlencode({"id": args.job_id, "lang": args.language})
    try:
        status, payload = _http.get_json(
            f"{_common.base_url()}{ISSUES_PATH}?{query}", headers=_common.headers()
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading issues: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status, f"read issues for {args.language}"),
        )
    if status == 404:
        die(_common.EXIT_API_ERROR, "that dub was not found in this organization.")
    if status != 200:
        die(
            _common.EXIT_API_ERROR,
            f"could not read issues ({status}): {_common.api_message(payload)}",
        )

    body = payload if isinstance(payload, dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    errors = normalize(data.get("errors"))
    warnings = normalize(data.get("warnings"))

    sys.stderr.write(
        f"[issues] {args.language}: {len(errors)} error(s), {len(warnings)} warning(s)\n"
    )

    print(
        json.dumps(
            {
                "status": "blocked" if errors else "clean",
                "language": args.language,
                "errors": errors,
                "warnings": warnings,
                "next_action": "fix_issues" if errors else "export_dub",
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
