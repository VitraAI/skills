#!/usr/bin/env python3
"""Phase 2 of a translate-video dub: submit the speaker-voice decisions,
resume the run, and stop once it is ready for review.

Deliberately does NOT export. Generation finishing is not the deliverable being
correct — a card can be missing audio or carry an invalid transcript — and a
render costs money. Export is a separate, explicit step (`export_dub.py`) that
refuses to render while errors remain.

Flow:
  1. GET  /v1/galaxy/translate-video/process-log/{jobId}/status   (read the gate)
  2. build the speakers map from --voice-map (per speaker, per target language):
       "clone"      -> the speaker's own voice (instant-clone)
       "keep"       -> leave the slot exactly as the gate had it
       "<voiceId>"  -> a catalog / saved-clone voice id
     Speakers/languages not named in --voice-map follow --voice-mode:
       "clone" (default)  -> each speaker's own voice
       "library_auto"     -> keep the voice the gate picked from the library
     A --voice-map already saved for this job (run manifest) is reused when
     --voice-map is omitted, so a re-run never re-asks the caller.
  3. POST /v1/galaxy/translate-video/process-log/{jobId}/human-validation
  4. poll status (with backoff) until completed
  5. print JSON: { status:"review_ready", job_id, target_languages,
                   next_action:"inspect_process" }

If the run fails, the JSON says so and names `retry_dub.py` — a failed run can
be resumed from the step that failed, without re-running or re-paying for the
steps that already succeeded.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Required arg: --job-id.
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _voices  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
STATUS_PATH = PL + "/{job_id}/status"
VALIDATE_PATH = PL + "/{job_id}/human-validation"

DEFAULT_POLL_INTERVAL = 12
DEFAULT_MAX_WAIT = 2400  # 40 min for synthesis + transcreation

FAILED_STATUSES = {"FAILED", "ERROR", "CANCELLED"}
DONE = "completed"

die = _common.die


def get_status(base: str, headers: dict, job_id: str) -> dict:
    try:
        status, payload = _http.get_json(
            base + STATUS_PATH.format(job_id=job_id), headers=headers
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading status: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status != 200:
        die(_common.EXIT_API_ERROR, f"status read failed ({status}): {_common.api_message(payload)}")
    return payload


def build_speakers(
    gate: dict, voice_map: dict, source_lang: str, targets: list[str], default: str = "clone",
    clones: list[dict] | None = None,
) -> dict:
    existing = ((gate.get("inputData") or {}).get("speakers")) or {}
    previews = ((gate.get("inputData") or {}).get("speakerPreview")) or {}
    result: dict = {}

    for sid, per_lang in existing.items():
        per_lang = per_lang or {}
        src_slot = dict(per_lang.get(source_lang, {}))
        preview = previews.get(sid, [{}])
        label = src_slot.get("label") or (preview[0] if preview else {}).get("name") or f"Speaker {sid}"
        gender = src_slot.get("gender") or ""
        src_slot.setdefault("label", label)
        if gender:
            src_slot.setdefault("gender", gender)

        out_slots = {source_lang: src_slot}
        choices = voice_map.get(sid, {})
        for lang in targets:
            choice = choices.get(lang) or choices.get("*") or default
            prior = dict(per_lang.get(lang, {}))
            if choice == "keep":
                out_slots[lang] = prior or {
                    "voiceName": label, "gender": gender, "label": label,
                    "voiceType": "instant-clone",
                }
            elif choice == "clone":
                out_slots[lang] = {
                    "voiceName": label, "gender": gender, "label": label,
                    "voiceType": "instant-clone",
                }
            else:  # a catalog / saved-clone voice id
                out_slots[lang] = {
                    **_voices.as_voice(choice, clones or [], prior.get("voiceName") or ""),
                    "gender": gender, "label": label,
                }
        result[sid] = out_slots
    return result


def submit_validation(base: str, headers: dict, job_id: str, task_id: str, speakers: dict) -> None:
    body = {"taskIdentifier": task_id, "approved": True, "speakers": speakers}
    try:
        status, payload = _http.post_json(
            base + VALIDATE_PATH.format(job_id=job_id), headers, body
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error on human-validation: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "approve this dub"))
    if status == 409:
        die(_common.EXIT_API_ERROR, "run is not awaiting validation (already resumed?). Check status.")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"human-validation failed ({status}): {_common.api_message(payload)}")


def poll_status(base: str, headers: dict, job_id: str, interval: int, max_wait: int) -> None:
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=interval)
    last = None
    while True:
        p = get_status(base, headers, job_id)
        state = p.get("status")
        if state != last:
            sys.stderr.write(f"[poll] job={job_id} status={state}\n")
            last = state
        if p.get("isFinished") and str(state).lower() == DONE:
            return
        if str(state).upper() in FAILED_STATUSES:
            print(
                json.dumps(
                    {
                        "status": "failed",
                        "job_id": job_id,
                        "error": p.get("errorMessage"),
                        # Resumes from the failed step; finished steps are not
                        # re-run or re-charged.
                        "next_action": "retry_dub",
                    }
                )
            )
            sys.exit(_common.EXIT_API_ERROR)
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, f"timed out after {max_wait}s. job_id={job_id}")
        time.sleep(_http.next_poll(p, delays))


def main() -> int:
    parser = argparse.ArgumentParser(description="Phase 2: submit voices, resume, stop when ready for review.")
    parser.add_argument("--job-id", required=True, help="job_id from dub_video.py (internal handle).")
    parser.add_argument(
        "--voice-map",
        default=None,
        help=(
            'JSON: { "<speakerId>": { "<langKey>": "clone" | "keep" | "<voiceId>" } }. '
            '"*" as the lang applies to every target language. Omitted '
            'speakers/langs default to "clone" (the speaker\'s own voice).'
        ),
    )
    parser.add_argument(
        "--voice-mode",
        choices=("clone", "library_auto"),
        help='Choice for speakers/languages not in --voice-map: "clone" '
             '(default) or "library_auto" (keep the gate\'s library voice).',
    )
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    saved = _common.load_manifest(args.job_id)
    try:
        voice_map = (
            json.loads(args.voice_map) if args.voice_map is not None
            else saved.get("voice_map") or {}
        )
        if not isinstance(voice_map, dict):
            raise ValueError
    except ValueError:
        die(_common.EXIT_API_ERROR, "--voice-map must be a JSON object")
    voice_mode = args.voice_mode or saved.get("voice_mode") or "clone"

    base = _common.base_url()
    headers = _common.headers()

    gate = get_status(base, headers, args.job_id)
    if not gate.get("awaitingHumanValidation"):
        state = str(gate.get("status") or "").lower()
        # "running" alone is ambiguous — it is also the state BEFORE the gate.
        # Only the manifest knows voices were submitted.
        if state == "completed" or (state == "running" and saved.get("stage") == "generating"):
            # Voices were already submitted (this command was interrupted, or
            # is being re-run): pick the run up instead of failing.
            sys.stderr.write(f"[resume] voices already submitted; run is {state}\n")
            if state == "running":
                poll_status(base, headers, args.job_id, args.poll_interval, args.max_wait)
            checkpoint = _common.update_manifest(args.job_id, stage="review_ready")
            print(json.dumps({
                "status": "review_ready",
                "job_id": args.job_id,
                "target_languages": gate.get("targetLanguages") or [],
                "next_action": "inspect_process",
                "checkpoint": str(checkpoint),
            }))
            return _common.EXIT_OK
        die(
            _common.EXIT_API_ERROR,
            f"job {args.job_id} is not at the voice gate "
            f"(status={gate.get('status')}). Nothing to resume.",
        )
    task_id = gate.get("humanValidationTaskIdentifier")
    source_lang = gate.get("sourceLanguage") or ""
    targets = gate.get("targetLanguages") or []
    if not task_id or not targets:
        die(_common.EXIT_API_ERROR, f"gate payload missing task/targets: {json.dumps(gate)[:600]}")

    speakers = build_speakers(
        gate, voice_map, source_lang, targets,
        "keep" if voice_mode == "library_auto" else "clone",
        _voices.list_cloned(base, headers),
    )
    # Saved BEFORE submitting: if this process dies after the gate is answered,
    # the decision is still on record for add_language and for a re-run.
    # Recorded BEFORE submitting: if the reply is lost (timeout, connection
    # reset) the submission may still have landed, and a re-run must then pick
    # up the generating run rather than refuse it. Safe if it did NOT land: a
    # re-run checks the gate first and simply submits again.
    _common.update_manifest(
        args.job_id, voice_map=voice_map, voice_mode=voice_mode, stage="generating"
    )
    submit_validation(base, headers, args.job_id, task_id, speakers)
    sys.stderr.write(f"[resume] job={args.job_id} approved, {len(speakers)} speaker(s)\n")

    poll_status(base, headers, args.job_id, args.poll_interval, args.max_wait)
    sys.stderr.write("[resume] run completed — ready for review\n")
    checkpoint = _common.update_manifest(args.job_id, stage="review_ready")

    print(
        json.dumps(
            {
                "status": "review_ready",
                "job_id": args.job_id,
                "target_languages": targets,
                "next_action": "inspect_process",
                "checkpoint": str(checkpoint),
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
