#!/usr/bin/env python3
"""Regenerate the speech of selected cards in ONE language — not the whole dub.

The same background job as the editor's "Generate" buttons:

  POST .../process-log/{jobId}/generate-all
       { targetLanguage, transcriptIds: [...] }   exactly these cards
       { targetLanguage, forceAll: false }        (--missing) only cards with no audio
  GET  .../process-log/{jobId}/pending-children   wait for it

Audio only: text, rate and timing are untouched. Use it after patch_cards
(its `audio_stale` list — `--stale` reads it from the run manifest) or for
cards list_issues reports as missing audio.

Verifies instead of trusting the job: re-reads the cards afterwards and reports
per card whether the audio is present and CHANGED. A regenerated clip keeps the
same url, so "changed" is decided by hashing the audio file before and after;
if the file cannot be fetched, by its length and rate, marked `verified: false`.
A card whose audio did not change is reported, not counted as fixed.

Prints JSON:
  { "status": "regenerated" | "partial" | "failed", "language",
    "cards": [{ card_id, audio_changed, verified, has_audio, duration_seconds,
                audio_sha256 }],
    "next_action": "list_issues" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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

PL = "/v1/galaxy/translate-video/process-log"
GENERATE_PATH = PL + "/{job_id}/generate-all"
OPERATION = "GENERATE_ALL"
DEFAULT_MAX_WAIT = 1800

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Regenerate speech for selected cards.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--language", required=True, help="Target language key.")
    which = parser.add_mutually_exclusive_group(required=True)
    which.add_argument("--card-ids", help="Comma-separated card ids.")
    which.add_argument(
        "--stale", action="store_true",
        help="The cards patch_cards reported as audio_stale (from the run manifest).",
    )
    which.add_argument(
        "--missing", action="store_true", help="Every card that has no audio."
    )
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()
    lang = args.language
    saved = _common.load_manifest(args.job_id)

    cards, _ = _cards.read_editor(base, headers, args.job_id)
    index = _cards.by_id(cards)

    if args.missing:
        ids = [cid for cid, c in index.items() if _cards.block(c, lang) and not _cards.audio_of(c, lang)]
    elif args.stale:
        ids = list(((saved.get("audio_stale") or {}).get(lang)) or [])
    else:
        ids = [x.strip() for x in args.card_ids.split(",") if x.strip()]

    unknown = [cid for cid in ids if cid not in index or not _cards.block(index[cid], lang)]
    if unknown:
        die(_common.EXIT_API_ERROR, f"not {lang} cards of this dub: {', '.join(unknown)}")
    if not ids:
        print(json.dumps({"status": "unchanged", "language": lang, "cards": [],
                          "next_action": "list_issues"}))
        return _common.EXIT_OK

    before = {cid: _cards.fingerprint(index[cid], lang) for cid in ids}

    # One regeneration at a time per language: if one is already running, wait
    # for it rather than paying for a second.
    running = _jobs.active_child(base, headers, args.job_id, OPERATION, lang)
    if running:
        child_id = running["id"]
        sys.stderr.write(f"[regenerate] a regeneration for {lang} is already running; waiting\n")
    else:
        # Scoped by ids even for --missing, so the job covers exactly the cards
        # reported here — not cards that lose audio in the meantime.
        body = {"targetLanguage": lang, "forceAll": False, "transcriptIds": ids}
        try:
            status, payload = _http.post_json(base + GENERATE_PATH.format(job_id=args.job_id), headers, body)
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error starting regeneration: {e}")
        if status in (401, 403):
            die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "regenerate speech"))
        if status not in (200, 201):
            die(_common.EXIT_API_ERROR, f"could not start regeneration ({status}): {_common.api_message(payload)}")
        child_id = (payload or {}).get("id")
        if not child_id:
            die(_common.EXIT_API_ERROR, "the server did not return the regeneration job.")

    row = _jobs.wait_for_child(base, headers, args.job_id, child_id, f"regenerate {lang}", args.max_wait)
    if row.get("status") == _jobs.FAILED:
        print(json.dumps({"status": "failed", "language": lang,
                          "error": row.get("errorMessage") or "regeneration failed",
                          "next_action": "regenerate_cards"}))
        return _common.EXIT_API_ERROR

    after_cards, revision = _cards.read_editor(base, headers, args.job_id)
    after = _cards.by_id(after_cards)
    report, fixed = [], []
    for cid in ids:
        audio = _cards.fingerprint(after.get(cid, {}), lang)
        prior = before.get(cid) or {}
        verified = True
        if not audio:
            changed = False
        elif not prior:
            changed = True  # had no audio, has some now
        elif audio.get("sha256") and prior.get("sha256"):
            changed = audio["sha256"] != prior["sha256"]
        else:
            verified = False
            changed = (audio.get("duration_seconds"), audio.get("rate")) != (
                prior.get("duration_seconds"), prior.get("rate"))
        report.append({
            "card_id": cid,
            "has_audio": bool(audio),
            "audio_changed": changed,
            "verified": verified,
            "duration_seconds": audio.get("duration_seconds"),
            "audio_sha256": audio.get("sha256"),
        })
        if changed:
            fixed.append(cid)

    stale = [c for c in ((saved.get("audio_stale") or {}).get(lang) or []) if c not in fixed]
    _common.update_manifest(args.job_id, audio_stale={lang: stale}, revision=revision)

    all_ok = len(fixed) == len(ids)
    print(json.dumps({
        "status": "regenerated" if all_ok else "partial",
        "language": lang,
        "cards": report,
        "next_action": "list_issues",
    }))
    return _common.EXIT_OK if all_ok else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
