"""A job's progress as the Vitra API reports it, in the steps the webapp shows.

Single source: `sync-lib.sh` copies this file into the video skills. Edit it
here only, then run the sync.

The status response carries `progressSteps` ({percent, summary, steps}); this
only relays it, trimmed for the reader. A server without it gets the overall
percent and state.
"""

from __future__ import annotations


def run_progress(status: dict) -> dict:
    """{percent, summary, steps?} for a status payload (GET .../status).

    `steps` is left out once the job is done: listing finished steps again
    only costs the reader tokens.
    """
    given = status.get("progressSteps")
    if isinstance(given, dict) and given.get("summary"):
        if given.get("summary") == "Done":
            return {"percent": 100, "summary": "Done"}
        return {k: given[k] for k in ("percent", "summary", "steps") if k in given}

    state = str(status.get("status") or "").lower()
    try:
        percent = max(0, min(100, int(float(status.get("progress") or 0))))
    except (TypeError, ValueError):
        percent = 0
    if state == "completed":
        return {"percent": 100, "summary": "Done"}
    if status.get("awaitingHumanValidation"):
        return {"percent": percent, "summary": "Waiting for your decision"}
    if state in ("failed", "cancelled"):
        return {"percent": percent, "summary": f"Stopped ({state})"}
    return {"percent": percent, "summary": f"Working, {percent}%"}


def line(progress: dict) -> str:
    """One stderr line for a poll loop."""
    return f"[progress] {progress['summary']} (overall {progress['percent']}%)"


# The dubbing scripts' original name.
dub_progress = run_progress
