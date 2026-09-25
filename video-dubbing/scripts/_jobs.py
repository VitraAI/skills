"""Child jobs of a dub: add-language, generate (regenerate audio), autofix.

Each of those starts a CHILD process of the dub and returns its id at once;
the work runs in the background and merges into the dub when it finishes.
This waits for one the way the webapp's Process Hub does — by reading the
dub's `pending-children` list — so the skill and the editor see the same state.
"""

from __future__ import annotations

import sys
import time

import _common
import _http

PL = "/v1/galaxy/translate-video/process-log"
CHILDREN_PATH = PL + "/{job_id}/pending-children"

# Process Hub statuses (see mapProcessStatusToHubStatus on the server).
DONE = "DONE"
FAILED = "FAILED"


def list_children(base: str, headers: dict, job_id: str) -> list[dict]:
    try:
        status, payload = _http.get_json(
            base + CHILDREN_PATH.format(job_id=job_id), headers=headers
        )
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error reading background jobs: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this dub"))
    if status != 200:
        _common.die(
            _common.EXIT_API_ERROR,
            f"could not read background jobs ({status}): {_common.api_message(payload)}",
        )
    rows = (payload or {}).get("data") if isinstance(payload, dict) else None
    return [r for r in rows or [] if isinstance(r, dict)]


def active_child(base: str, headers: dict, job_id: str, operation: str, language: str) -> dict | None:
    """An unfinished child of this kind for this language, if one is running."""
    for row in list_children(base, headers, job_id):
        if (
            row.get("operation") == operation
            and row.get("language") == language
            and row.get("status") not in (DONE, FAILED)
        ):
            return row
    return None


def wait_for_child(
    base: str,
    headers: dict,
    job_id: str,
    child_id: str,
    label: str,
    max_wait: int,
    first_delay: float = 10.0,
) -> dict:
    """Poll until the child is DONE or FAILED; return its row.

    Times out with exit 5 and a message that says the job is still running —
    re-running the command reconciles to the same job instead of starting one.
    """
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=first_delay)
    last = None
    while True:
        row = next(
            (r for r in list_children(base, headers, job_id) if r.get("id") == child_id),
            None,
        )
        state = (row or {}).get("status")
        if state != last:
            sys.stderr.write(f"[{label}] status={state} progress={(row or {}).get('progress')}\n")
            last = state
        if row is not None and state in (DONE, FAILED):
            return row
        if time.monotonic() >= deadline:
            _common.die(
                _common.EXIT_TIMEOUT,
                f"{label} is still running after {max_wait}s. Run the same "
                "command again to keep waiting — it will not start a second job.",
            )
        time.sleep(next(delays))
