#!/usr/bin/env python3
"""Export ONE reviewed language, refusing to render while errors remain.

Deliberately separate from generation. Generation finishing does not mean the
dub is correct — transcripts can be invalid, cards can be missing audio — and a
render costs money, so export is a decision, not a continuation.

  GET  .../transcript/issues     -> refuse if any errors
  POST .../process-log/export-video  { ignoreTranscriptErrors: false }
  GET  .../process-log/{childId}/editor-output  -> the rendered media url

`ignoreTranscriptErrors: false` makes the SERVER enforce the same rule, so a
race between the check and the render cannot slip an invalid transcript
through. The local check exists to fail fast with a useful message.

Also refused (never rendered) when:
  * cards still speak an OLD line — `audio_stale` in the run manifest, left by
    patch_cards / split: regenerate them first (next_action regenerate_cards);
  * --revision is given and the transcript has changed since that review:
    the render would not be the version that was checked.

An export already recorded for this language at the same revision and
settings is returned as-is instead of rendered again. A render the server
marks FAILED is reported at once, not waited on until the timeout.

Prints JSON:
  { "status": "exported", "language": "...", "export_id": "...",
    "media_url": "...", "next_action": "download_export" }

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
ISSUES_PATH = PL + "/transcript/issues"
EXPORT_PATH = PL + "/export-video"
EDITOR_OUTPUT_PATH = PL + "/{child_id}/editor-output"

DEFAULT_POLL_INTERVAL = 10
DEFAULT_MAX_WAIT = 1800  # a render is minutes, not seconds

die = _common.die


def count_errors(base: str, headers: dict, job_id: str, lang: str) -> list:
    """Blocking errors for this language. Empty means safe to render."""
    query = urlencode({"id": job_id, "lang": lang})
    try:
        status, payload = _http.get_json(f"{base}{ISSUES_PATH}?{query}", headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error checking issues: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read issues"))
    if status != 200:
        die(
            _common.EXIT_API_ERROR,
            f"could not check issues before export ({status}): "
            f"{_common.api_message(payload)}",
        )
    body = payload if isinstance(payload, dict) else {}
    data = body.get("data") if isinstance(body.get("data"), dict) else body
    errors = data.get("errors")
    return errors if isinstance(errors, list) else []


def transcript_revision(base: str, headers: dict, job_id: str) -> int | None:
    """The transcript's current revision, or None if the server cannot say.

    Part of the export's idempotency key: the same revision means the same
    deliverable, so a retried export is replayed rather than rendered twice —
    while any edit since moves the revision and makes a re-export genuinely new.
    """
    try:
        status, payload = _http.get_json(
            base
            + EDITOR_OUTPUT_PATH.format(child_id=job_id)
            + "?includeRevision=true",
            headers=headers,
        )
    except _http.NetworkError:
        return None
    if status != 200:
        return None
    revision = ((payload or {}).get("data") or {}).get("revision")
    return revision if isinstance(revision, int) else None


def start_export(
    base: str, headers: dict, job_id: str, lang: str, resolution: str, lip_sync: bool
) -> str:
    body = {
        "processId": job_id,
        "resolution": resolution,
        "videoLanguage": lang,
        "scalingFactor": {"x": 1, "y": 1},
        # The server refuses invalid transcripts when this is false. Never send
        # true from here: it is the exact bypass this command exists to close.
        "ignoreTranscriptErrors": False,
    }
    if lip_sync:
        body["lipSync"] = True

    # Without a known revision there is no safe key: a key blind to edits
    # would replay a stale render after the transcript changed. Then the export
    # is simply not deduplicated — the pre-existing behaviour.
    revision = transcript_revision(base, headers, job_id)
    export_headers = dict(headers)
    if revision is not None:
        export_headers["Idempotency-Key"] = _common.idempotency_key(
            "export", job_id, lang, resolution, lip_sync, revision
        )

    try:
        status, payload = _http.post_json(base + EXPORT_PATH, export_headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the export: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "export this dub"))
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"export failed to start ({status}): {_common.api_message(payload)}",
        )

    data = (payload or {}).get("data") or {}
    child_id = data.get("id")
    if not child_id:
        die(
            _common.EXIT_API_ERROR,
            f"no export id in the response: {_common.api_message(payload)}",
        )
    return child_id


def export_failed(base: str, headers: dict, job_id: str, child_id: str) -> str | None:
    """The failure reason if the server marked this render FAILED, else None."""
    import _jobs

    for row in _jobs.list_children(base, headers, job_id):
        if row.get("id") == child_id and row.get("status") == _jobs.FAILED:
            return row.get("errorMessage") or "the render failed"
    return None


def poll_media(
    base: str, headers: dict, child_id: str, interval: int, max_wait: int,
    job_id: str | None = None,
) -> str:
    """Wait for the render, then return the stored media URL."""
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=interval)
    while True:
        try:
            status, payload = _http.get_json(
                base + EDITOR_OUTPUT_PATH.format(child_id=child_id), headers=headers
            )
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error reading the export: {e}")
        if status == 200:
            data = ((payload or {}).get("data") or {}).get("data") or {}
            bundle = data
            out = data.get("OUTPUT")
            if isinstance(out, list) and out and isinstance(out[0], dict):
                bundle = out[0]
            media = bundle.get("video") or bundle.get("audio")
            if isinstance(media, str) and media:
                return media

        if job_id:
            reason = export_failed(base, headers, job_id, child_id)
            if reason:
                die(_common.EXIT_API_ERROR, f"the export failed: {reason}",
                    error_code="EXPORT_FAILED", retryable=True, export_id=child_id)
        if time.monotonic() >= deadline:
            die(
                _common.EXIT_TIMEOUT,
                f"the export did not finish within {max_wait}s. It may still be "
                "rendering — re-run download_export with this export id rather "
                "than exporting again.",
            )
        time.sleep(next(delays))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Export one reviewed language, refusing to render while errors remain."
    )
    parser.add_argument("--job-id", required=True, help="The dub's job id.")
    parser.add_argument(
        "--language", required=True, help="Target language key to export."
    )
    parser.add_argument(
        "--resolution",
        default="1080",
        choices=["4K", "2K", "1080", "720", "480", "360"],
    )
    parser.add_argument("--lip-sync", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Render even though blocking errors exist. The server still "
             "validates, so this only skips the local pre-check.",
    )
    parser.add_argument(
        "--revision", type=int,
        help="The transcript revision that was reviewed; refuses if it has changed since.",
    )
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()
    lang = args.language
    saved = _common.load_manifest(args.job_id)

    def refuse(reason: str, message: str, next_action: str, **extra) -> int:
        print(json.dumps({"status": "refused", "reason": reason, "language": lang,
                          "message": message, "next_action": next_action, **extra}))
        sys.stderr.write(f"[export] refused — {message}\n")
        return _common.EXIT_OK

    import _cards

    cards, _ = _cards.read_editor(base, headers, args.job_id)
    index = _cards.by_id(cards)
    # Only cards that still exist AND still have audio can be speaking an old
    # line; a card with no audio is a blocking issue, reported below.
    stale = _common.prune_stale(
        args.job_id, lang, lambda cid: cid in index and bool(_cards.audio_of(index[cid], lang))
    )
    if stale and not args.force:
        return refuse("stale_audio",
                      f"{len(stale)} card(s) still speak their old line", "regenerate_cards",
                      cards=stale)

    revision = transcript_revision(base, headers, args.job_id)
    if args.revision is not None and revision is not None and revision != args.revision:
        return refuse("revision_changed",
                      f"the transcript changed since review (revision {args.revision} -> {revision})",
                      "inspect_process", current_revision=revision)

    settings = {"resolution": args.resolution, "lip_sync": args.lip_sync, "revision": revision}
    prior = ((saved.get("exports") or {}).get(lang)) or {}
    if revision is not None and prior.get("media_url") and all(prior.get(k) == v for k, v in settings.items()):
        sys.stderr.write("[export] this exact version was already rendered; reusing it\n")
        print(json.dumps({"status": "exported", "language": lang, "export_id": prior["export_id"],
                          "media_url": prior["media_url"], "revision": revision, "reused": True,
                          "next_action": "download_export"}))
        return _common.EXIT_OK

    errors = count_errors(base, headers, args.job_id, args.language)
    if errors and not args.force:
        first = errors[0] if isinstance(errors[0], dict) else {}
        print(
            json.dumps(
                {
                    "status": "refused",
                    "reason": "blocking_issues",
                    "language": args.language,
                    "error_count": len(errors),
                    "first_error": {
                        "card_id": first.get("transcriptId"),
                        "type": first.get("type"),
                        "message": first.get("msg"),
                    },
                    "next_action": "list_issues",
                }
            )
        )
        sys.stderr.write(
            f"[export] refused — {len(errors)} blocking issue(s) in "
            f"{args.language}. Fix them, then export.\n"
        )
        return _common.EXIT_OK

    sys.stderr.write(f"[export] rendering {args.language}…\n")
    export_id = start_export(
        base, headers, args.job_id, args.language, args.resolution, args.lip_sync
    )
    _common.update_manifest(args.job_id, exports={lang: {"export_id": export_id, **settings}})
    media_url = poll_media(
        base, headers, export_id, args.poll_interval, args.max_wait, args.job_id
    )
    _common.update_manifest(args.job_id, exports={lang: {"export_id": export_id, "media_url": media_url, **settings}})

    print(
        json.dumps(
            {
                "status": "exported",
                "language": args.language,
                "export_id": export_id,
                "media_url": media_url,
                "revision": revision,
                "next_action": "download_export",
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
