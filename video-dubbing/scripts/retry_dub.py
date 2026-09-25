#!/usr/bin/env python3
"""Retry a FAILED dub from the step that failed.

A retry resumes the same run instead of starting over, so the steps that
already succeeded (transcription, translation, voices already generated) are
not re-run or charged again. Publishing a new dub would pay for all of them
a second time.

Flow:
  1. POST /v1/galaxy/translate-video/process-log/{jobId}/retry
  2. poll GET .../{jobId}/status (with backoff) until the run
       - stops at the voice gate  -> next_action "resume_dub"
       - completes                -> next_action "inspect_process"
       - fails again              -> stop; do NOT loop on retries

Prints JSON:
  { "status": "awaiting_voices" | "review_ready" | "failed",
    "job_id": "...", "error": "...", "next_action": "..." }

The server refuses a retry (409) when the run is not failed, never started,
or another run of the same dub (another language, an export) is in progress.
Those are reported as-is; none of them is fixed by retrying again.

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

PL = "/v1/galaxy/translate-video/process-log"
RETRY_PATH = PL + "/{job_id}/retry"
STATUS_PATH = PL + "/{job_id}/status"

DEFAULT_POLL_INTERVAL = 12
DEFAULT_MAX_WAIT = 2400  # same budget as resume_dub: synthesis can be long

FAILED_STATUSES = {"FAILED", "ERROR", "CANCELLED"}

die = _common.die


def emit(status: str, job_id: str, next_action: str | None, error: object = None) -> None:
    out = {"status": status, "job_id": job_id, "next_action": next_action}
    if error:
        out["error"] = error
    print(json.dumps(out))


def start_retry(base: str, headers: dict, job_id: str) -> None:
    try:
        status, payload = _http.post_json(
            base + RETRY_PATH.format(job_id=job_id), headers, {}
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the retry: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "retry this dub"))
    if status == 404:
        die(
            _common.EXIT_API_ERROR,
            "that dub was not found in this organization, or this server does "
            "not support retrying yet.",
        )
    if status == 409:
        # Not failed / never started / another run in progress. Retrying again
        # will not change any of these, so say why and stop.
        die(
            _common.EXIT_API_ERROR,
            f"the dub cannot be retried right now: {_common.api_message(payload)}",
        )
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"retry failed ({status}): {_common.api_message(payload)}",
        )


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
        die(
            _common.EXIT_API_ERROR,
            f"status read failed ({status}): {_common.api_message(payload)}",
        )
    return payload if isinstance(payload, dict) else {}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Retry a failed dub from the step that failed."
    )
    parser.add_argument("--job-id", required=True, help="The failed dub's job id.")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    start_retry(base, headers, args.job_id)
    _common.update_manifest(args.job_id, stage="retrying")
    sys.stderr.write(f"[retry] job={args.job_id} resumed from the failed step\n")

    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=args.poll_interval)
    last = None
    while True:
        p = get_status(base, headers, args.job_id)
        state = p.get("status")
        if state != last:
            sys.stderr.write(f"[poll] job={args.job_id} status={state}\n")
            last = state
        if p.get("awaitingHumanValidation"):
            _common.update_manifest(args.job_id, stage="awaiting_voices")
            emit("awaiting_voices", args.job_id, "resume_dub")
            return _common.EXIT_OK
        if p.get("isFinished") and str(state).lower() == "completed":
            _common.update_manifest(args.job_id, stage="review_ready")
            emit("review_ready", args.job_id, "inspect_process")
            return _common.EXIT_OK
        if str(state).upper() in FAILED_STATUSES:
            # Failed twice at (likely) the same step: a third retry is rarely
            # the answer. Hand the error to the user instead of looping.
            emit("failed", args.job_id, None, p.get("errorMessage") or "run failed")
            return _common.EXIT_API_ERROR
        if time.monotonic() >= deadline:
            die(
                _common.EXIT_TIMEOUT,
                f"timed out after {args.max_wait}s; the retry is still running. "
                f"job_id={args.job_id}",
            )
        time.sleep(_http.next_poll(p, delays))


if __name__ == "__main__":
    sys.exit(main())
