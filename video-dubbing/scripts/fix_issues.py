#!/usr/bin/env python3
"""Repair the issues blocking export for ONE language — the editor's
"Fix all issues", bounded, with every change disclosed.

  GET  .../transcript/issues?id&lang            what is wrong
  POST .../process-log/{jobId}/autofix-all      { targetLanguage }   (rates, fit)
  POST .../process-log/{jobId}/generate-all     { targetLanguage, transcriptIds }
                                                (only missing audio)
  GET  .../process-log/{jobId}/pending-children wait for the job
  GET  .../editor-output + issues again         verify

The repair ladder, one rung per attempt:
  * Only "No Audio" errors  -> regenerate exactly those cards (audio only,
    nothing else can change).
  * Anything autofix handles (rate errors, and missing audio alongside them)
    -> autofix: clamps rates, trims a line's end time into its gap, and may
    SHORTEN a translation so it fits, then re-voices the cards it changed.
  * Timing / content errors autofix cannot fix are reported, never guessed at:
    fix them with patch_cards or in the editor.

Every value that changed is reported (text, rate, start/end, audio). A change
to text a reviewer had APPROVED is called out separately under
`approved_text_changed` — show it to the caller; nothing is changed silently.

Stops after --budget attempts (default 1) and reports what is left, with the
exact cards. It never loops until "clean".

Prints JSON:
  { "status": "clean" | "partial" | "failed", "language", "attempts",
    "changes": [{card_id, field, before, after}], "approved_text_changed": [...],
    "remaining_errors": [...], "remaining_warnings": [...], "next_action": ... }

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
import _cards  # noqa: E402
import _common  # noqa: E402
import _http  # noqa: E402
import _jobs  # noqa: E402
from list_issues import normalize  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
ISSUES_PATH = PL + "/transcript/issues"
AUTOFIX_PATH = PL + "/{job_id}/autofix-all"
GENERATE_PATH = PL + "/{job_id}/generate-all"

NO_AUDIO = "No Audio Error"
AUTOFIXABLE = {"Rate Error", NO_AUDIO}
DEFAULT_MAX_WAIT = 2400

die = _common.die


def read_issues(base: str, headers: dict, job_id: str, lang: str) -> tuple[list, list]:
    query = urlencode({"id": job_id, "lang": lang})
    try:
        status, payload = _http.get_json(f"{base}{ISSUES_PATH}?{query}", headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading issues: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, f"read issues for {lang}"))
    if status != 200:
        die(_common.EXIT_API_ERROR, f"could not read issues ({status}): {_common.api_message(payload)}")
    body = payload if isinstance(payload, dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    return normalize(data.get("errors")), normalize(data.get("warnings"))


def snapshot(cards: list, lang: str) -> dict[str, dict]:
    """The values a repair can change, per card."""
    out = {}
    for card in cards:
        b = _cards.block(card, lang)
        if not b:
            continue
        tr = b.get("tr") if isinstance(b.get("tr"), dict) else {}
        v = b.get("v") if isinstance(b.get("v"), dict) else {}
        a = _cards.audio_of(card, lang)
        out[str(card.get("id"))] = {
            "text": tr.get("text"),
            "start": v.get("st"),
            "end": v.get("et"),
            "rate": a.get("rate"),
            "audio_seconds": a.get("duration_seconds"),
            "has_audio": bool(a),
            "_approved": b.get("rs") == "a",
        }
    return out


def diff(before: dict, after: dict) -> tuple[list, list]:
    changes, approved = [], []
    for cid, prev in before.items():
        now = after.get(cid)
        if now is None:
            changes.append({"card_id": cid, "field": "card", "before": "present", "after": "removed"})
            continue
        for field in ("text", "start", "end", "rate", "audio_seconds", "has_audio"):
            if prev[field] != now[field]:
                change = {"card_id": cid, "field": field, "before": prev[field], "after": now[field]}
                changes.append(change)
                if field == "text" and prev["_approved"]:
                    approved.append(change)
    return changes, approved


def start_job(base: str, headers: dict, url: str, body: dict, what: str) -> str:
    try:
        status, payload = _http.post_json(url, headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting {what}: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not start {what} ({status}): {_common.api_message(payload)}")
    job = (payload or {}).get("id")
    if not job:
        die(_common.EXIT_API_ERROR, f"the server did not return the {what} job.")
    return job


def main() -> int:
    parser = argparse.ArgumentParser(description="Repair blocking issues for one language, bounded.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True, help="Target language key.")
    parser.add_argument("--budget", type=int, default=1, help="Repair attempts before stopping (default 1).")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()
    lang = args.language

    errors, warnings = read_issues(base, headers, args.job_id, lang)
    all_changes, all_approved, attempts = [], [], 0

    while errors and attempts < max(1, args.budget):
        fixable = [e for e in errors if e["type"] in AUTOFIXABLE]
        if not fixable:
            break  # only errors a repair job cannot fix remain
        attempts += 1
        before_cards, _ = _cards.read_editor(base, headers, args.job_id)
        before = snapshot(before_cards, lang)

        only_audio = all(e["type"] == NO_AUDIO for e in fixable)
        operation = "GENERATE_ALL" if only_audio else "AUTOFIX"
        running = _jobs.active_child(base, headers, args.job_id, operation, lang)
        if running:
            child = running["id"]
            sys.stderr.write(f"[fix] a {operation.lower()} for {lang} is already running; waiting\n")
        elif only_audio:
            ids = sorted({e["card_id"] for e in fixable if e["card_id"]})
            child = start_job(base, headers, base + GENERATE_PATH.format(job_id=args.job_id),
                              {"targetLanguage": lang, "forceAll": False, "transcriptIds": ids},
                              "regenerating missing audio")
        else:
            child = start_job(base, headers, base + AUTOFIX_PATH.format(job_id=args.job_id),
                              {"targetLanguage": lang}, "fixing issues")
        sys.stderr.write(f"[fix] attempt {attempts}: {operation.lower()} for {len(fixable)} issue(s)\n")

        row = _jobs.wait_for_child(base, headers, args.job_id, child, f"fix {lang}", args.max_wait)
        if row.get("status") == _jobs.FAILED:
            print(json.dumps({
                "status": "failed", "language": lang, "attempts": attempts,
                "error": row.get("errorMessage") or "the repair job failed",
                "changes": all_changes, "approved_text_changed": all_approved,
                "remaining_errors": errors, "next_action": None,
            }))
            return _common.EXIT_API_ERROR

        after_cards, revision = _cards.read_editor(base, headers, args.job_id)
        changes, approved = diff(before, snapshot(after_cards, lang))
        revoiced = {c["card_id"] for c in changes if c["field"] in ("audio_seconds", "has_audio")}
        _common.prune_stale(args.job_id, lang, lambda cid: cid not in revoiced)
        all_changes += changes
        all_approved += approved
        _common.update_manifest(args.job_id, revision=revision)
        errors, warnings = read_issues(base, headers, args.job_id, lang)

    status = "clean" if not errors else "partial"
    print(json.dumps({
        "status": status,
        "language": lang,
        "attempts": attempts,
        "changes": all_changes,
        "approved_text_changed": all_approved,
        "remaining_errors": errors,
        "remaining_warnings": warnings,
        # Left over after the budget: timing/content errors need a person or
        # patch_cards — say which cards, do not retry blindly.
        "next_action": "export_dub" if not errors else "patch_cards",
    }))
    return _common.EXIT_OK if not errors else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
