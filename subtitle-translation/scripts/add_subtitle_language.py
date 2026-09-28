#!/usr/bin/env python3
"""Add translated subtitle languages to a subtitle job (or to a dub).

Single source: `sync-lib.sh` copies this file into the subtitle skills. Edit it
here only, then run the sync.

Translates the job's reviewed source lines into each new language and breaks
them into timed subtitles — no voices, nothing re-transcribed. The languages
queue and run one at a time on the server.

  POST .../process-log/{id}/add-languages   { languages: [{targetLanguage}], subtitles: true }
  GET  .../process-log/{id}/pending-children   wait for each (ADD_SUBTITLE_LANGUAGE)
  POST .../process-log/{id}/rollback-add-language   only for one that failed

Pass --expected-revision (from inspect_subtitles.py) after correcting the
source: if the subtitles changed since, nothing is added.

Re-running with a language already on the job waits for it (if it is still
being added) instead of adding it twice.

Prints JSON:
  { "status": "review_ready" | "partial" | "failed", "job_id",
    "added": [lang], "failed": [{"language", "error"}], "next_action" }

Charged per language. Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cards  # noqa: E402
import _common  # noqa: E402
import _http  # noqa: E402
import _jobs  # noqa: E402
import _tv  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
ADD_PATH = PL + "/{job_id}/add-languages"
ROLLBACK_PATH = PL + "/{job_id}/rollback-add-language"
OPERATION = "ADD_SUBTITLE_LANGUAGE"
MAX_PER_CALL = 20  # the API's limit per call
DEFAULT_MAX_WAIT = 1800

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Add translated subtitle languages.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", action="append", required=True, metavar="KEY",
                        help="Language key to add (repeatable), from list_languages.py.")
    parser.add_argument("--expected-revision", type=int,
                        help="The revision the source was reviewed at (inspect_subtitles.py).")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    langs = list(dict.fromkeys(args.language))
    if len(langs) > MAX_PER_CALL:
        die(_common.EXIT_API_ERROR, f"at most {MAX_PER_CALL} languages at once.")
    base, headers = _common.base_url(), _common.headers()
    row = _tv.get_status(base, headers, args.job_id)
    if row.get("sourceLanguage") in langs:
        die(_common.EXIT_API_ERROR, f"{row.get('sourceLanguage')} is the job's own language.")

    if args.expected_revision is not None:
        _, current = _cards.read_editor(base, headers, args.job_id)
        if current is not None and current != args.expected_revision:
            die(_common.EXIT_API_ERROR,
                f"the subtitles changed since they were reviewed ({args.expected_revision} -> {current}); "
                "nothing was added. Re-run inspect_subtitles.py and review again.",
                error_code="REVISION_CONFLICT", current_revision=current)

    # A language already on the job is either still being added (wait for it)
    # or done; only the rest are new.
    existing = set(row.get("targetLanguages") or [])
    children = _jobs.list_children(base, headers, args.job_id)
    waiting: dict[str, str] = {}
    for lang in [x for x in langs if x in existing]:
        latest = next((r for r in children if r.get("operation") == OPERATION and r.get("language") == lang), None)
        if latest and latest.get("status") not in (_jobs.DONE, _jobs.FAILED):
            waiting[lang] = latest["id"]
    new = [x for x in langs if x not in existing]

    if new:
        key = _common.idempotency_key("add-subtitle-languages", args.job_id, new, args.expected_revision)
        try:
            status, payload = _http.post_json(
                base + ADD_PATH.format(job_id=args.job_id), {**headers, "Idempotency-Key": key},
                {"languages": [{"targetLanguage": x} for x in new], "subtitles": True})
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error adding languages: {e}")
        if status in (401, 403):
            die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "add a language"))
        if status == 402:
            die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
                error_code="INSUFFICIENT_CREDITS")
        if status not in (200, 201):
            die(_common.EXIT_API_ERROR, f"could not add {', '.join(new)} ({status}): {_common.api_message(payload)}")
        for item in (payload or {}).get("accepted") or []:
            if isinstance(item, dict) and item.get("id"):
                waiting[item.get("targetLanguage")] = item["id"]
        sys.stderr.write(f"[subtitles] adding {', '.join(new)} (one at a time)\n")

    added, failed = [x for x in langs if x in existing and x not in waiting], []
    for lang, child_id in waiting.items():
        child = _jobs.wait_for_child(base, headers, args.job_id, child_id, f"add {lang}", args.max_wait)
        if child.get("status") == _jobs.FAILED:
            # Rolled back so the same command can simply be run again.
            try:
                _http.post_json(base + ROLLBACK_PATH.format(job_id=args.job_id), headers, {"targetLanguage": lang})
            except _http.NetworkError:
                pass
            failed.append({"language": lang, "error": child.get("errorMessage") or "adding the language failed"})
        else:
            added.append(lang)

    status = "review_ready" if not failed else ("partial" if added else "failed")
    print(json.dumps({
        "status": status, "job_id": args.job_id, "added": added, "failed": failed,
        "next_action": "add_subtitle_language" if failed and not added else "inspect_subtitles",
    }))
    return _common.EXIT_API_ERROR if status == "failed" else _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
