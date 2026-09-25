"""Progress of a dub, in the same steps the Vitra webapp shows.

A port of the webapp's process-loading timeline
(`galaxy/translate-video/components/shared/process-loading`: `config.ts` and
`helpers.ts`): the backend reports one entry per task in `tasks[]`, and the
webapp rolls those into six user-facing steps. Using the same titles and the
same arithmetic means the agent and the webapp never disagree about where a
dub is. Keep this in step with those two files.
"""

from __future__ import annotations

# (title, backend task identifiers that roll up into it) — VIDEO_TO_SPEECH_TRANSLATION.
DUB_STEPS: list[tuple[str, list[str]]] = [
    ("Analysing the video", ["DOWNLOAD", "AUDIO-EXTRACTOR", "AUDIO-SOURCE-SEPARATOR"]),
    ("Transcribing the video", ["TRANSCRIPTION-ENGINE"]),
    ("Translating the script", ["TRANSCREATION-ENGINE"]),
    ("Preparing the voices", ["INSTANT-VOICE-CLONING-ENGINE"]),
    ("Generating the voice-over", ["SPEECH-GENERATION-ENGINE"]),
    ("Wrapping up", ["AGGREGATE"]),
]

TERMINAL = {"completed", "failed", "cancelled"}


def _pct(task: dict) -> int:
    if str(task.get("status", "")).lower() == "completed":
        return 100
    try:
        return max(0, min(100, int(float(task.get("progress") or 0))))
    except (TypeError, ValueError):
        return 0


def _group_status(tasks: list[dict], process_status: str) -> str:
    if not tasks:
        return "pending"
    states = [str(t.get("status", "")).lower() for t in tasks]
    if all(s == "completed" for s in states):
        return "completed"
    if any(s in ("failed", "cancelled") for s in states) and process_status in ("failed", "cancelled"):
        return "error"
    if any(s == "running" or s in TERMINAL for s in states) or any(_pct(t) > 0 for t in tasks):
        return "in-progress"
    return "pending"


def _reconcile(statuses: list[str], process_status: str) -> list[str]:
    """A finished run never shows a spinner; a failed one marks where it stopped."""
    if process_status == "completed":
        return ["completed"] * len(statuses)
    if process_status in ("failed", "cancelled") and "error" not in statuses:
        if "in-progress" in statuses:
            active = statuses.index("in-progress")
        elif "completed" in statuses:
            active = min(len(statuses) - 1, len(statuses) - 1 - statuses[::-1].index("completed") + 1)
        else:
            active = 0
        return ["completed" if i < active else "error" if i == active else "pending"
                for i in range(len(statuses))]
    return statuses


def dub_progress(status: dict) -> dict:
    """{percent, summary, steps: [{title, status, percent}]} from a status payload.

    `status` is GET .../process-log/{id}/status. A step is `waiting-for-you`
    while the run is paused for the user's decision at that step (the voices).
    """
    process_status = str(status.get("status") or "").lower()
    by_id = {t.get("taskIdentifier"): t for t in (status.get("tasks") or []) if isinstance(t, dict)}
    groups = [[by_id[i] for i in ids if i in by_id] for _, ids in DUB_STEPS]

    statuses = _reconcile([_group_status(g, process_status) for g in groups], process_status)
    percents = [round(sum(_pct(t) for t in g) / len(g)) if g else 0 for g in groups]
    percents = [100 if s == "completed" else p for s, p in zip(statuses, percents)]

    waiting_on = status.get("humanValidationTaskIdentifier") if status.get("awaitingHumanValidation") else None
    if waiting_on:
        for i, (_, ids) in enumerate(DUB_STEPS):
            if waiting_on in ids:
                statuses[i] = "waiting-for-you"

    steps = [{"title": title, "status": s, "percent": p}
             for (title, _), s, p in zip(DUB_STEPS, statuses, percents)]
    try:
        overall = max(0, min(100, int(float(status.get("progress") or 0))))
    except (TypeError, ValueError):
        overall = 0
    if process_status == "completed":
        overall = 100

    current = next((i for i, s in enumerate(statuses) if s in ("waiting-for-you", "error", "in-progress")), None)
    if process_status == "completed":
        summary = "Done"
    elif current is None:
        summary = "Starting"
    else:
        step = steps[current]
        tail = {"waiting-for-you": "waiting for your decision", "error": "failed here"}.get(
            step["status"], f"{step['percent']}%")
        summary = f"Step {current + 1} of {len(steps)}: {step['title']}, {tail}"
    return {"percent": overall, "summary": summary, "steps": steps}


def line(progress: dict) -> str:
    """One stderr line for a poll loop."""
    return f"[progress] {progress['summary']} (overall {progress['percent']}%)"
