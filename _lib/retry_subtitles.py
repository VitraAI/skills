#!/usr/bin/env python3
"""Resume a failed subtitle job from the step that failed.

Single source: `sync-lib.sh` copies this file into the subtitle skills. Edit it
here only, then run the sync.

Finished steps are kept (nothing is uploaded or transcribed again).

  POST .../process-log/{id}/retry
  GET  .../process-log/{id}/status   until it finishes

Prints JSON: { "status": "review_ready" | "failed", "job_id", "progress",
               "next_action" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _progress  # noqa: E402
import _tv  # noqa: E402

RETRY_PATH = _tv.PL + "/{job_id}/retry"
DEFAULT_MAX_WAIT = 1800
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Resume a failed subtitle job.")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    try:
        status, payload = _http.post_json(base + RETRY_PATH.format(job_id=args.job_id), headers, {})
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the retry: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "retry this job"))
    if status == 404:
        die(_common.EXIT_API_ERROR, "that job was not found in this organization, or this server "
            "can't retry jobs yet; start it again with start_subtitles.py.")
    if status == 409:
        # Not failed, or already running: retrying again won't change that.
        die(_common.EXIT_API_ERROR, f"the job can't be retried right now: {_common.api_message(payload)}")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"retry failed ({status}): {_common.api_message(payload)}")

    row = _tv.wait(base, headers, args.job_id, args.max_wait)
    done = str(row.get("status") or "").lower() == "completed"
    out = {"status": "review_ready" if done else "failed", "job_id": args.job_id,
           "progress": _progress.run_progress(row),
           # Failed twice, likely at the same step: hand it to the user.
           "next_action": "inspect_subtitles" if done else None}
    if not done:
        out["error"] = row.get("errorMessage") or "the job failed again"
    print(json.dumps(out))
    return _common.EXIT_OK if done else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
