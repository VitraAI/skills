"""Config + auth (shared: `_core.py`, a copy of `_lib/_common.py`) plus
the video-dubbing run manifest, which only this skill uses.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

from _core import *  # noqa: F401,F403  (shared helpers, re-exported)


# ---------------------------------------------------------------------------
# Run manifest: the private record of one dub, so any command can pick the run
# up again after a crash, a closed terminal or a new session — without
# re-uploading, re-publishing or re-asking the caller about voices.
#
# One JSON file per job under ~/.vitra/video-dubbing/runs/ (override:
# VITRA_DUB_STATE_DIR), readable only by this user. It holds ids, hashes,
# revisions and choices — never the API key, never signed URLs.
# ---------------------------------------------------------------------------

STATE_DIR_VAR = "VITRA_DUB_STATE_DIR"


def state_dir() -> Path:
    override = os.environ.get(STATE_DIR_VAR, "").strip()
    root = Path(override).expanduser() if override else Path.home() / ".vitra" / "video-dubbing" / "runs"
    root.mkdir(parents=True, exist_ok=True)
    try:
        root.chmod(0o700)
    except OSError:
        pass
    return root


def manifest_path(job_id: str) -> Path:
    safe = "".join(ch for ch in job_id if ch.isalnum() or ch in "-_")
    return state_dir() / f"{safe}.json"


def load_manifest(job_id: str) -> dict:
    import json

    path = manifest_path(job_id)
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text())
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def update_manifest(job_id: str, **fields: object) -> Path:
    """Merge fields into the job's manifest (dicts merge one level deep).

    Written to a temp file then renamed, so a crash mid-write never leaves a
    half manifest. Best effort: a read-only home must not fail the dub itself.
    """
    import json
    import time

    data = load_manifest(job_id)
    for key, value in fields.items():
        if isinstance(value, dict) and isinstance(data.get(key), dict):
            data[key] = {**data[key], **value}
        else:
            data[key] = value
    data["job_id"] = job_id
    data["updated_at"] = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    path = manifest_path(job_id)
    try:
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, sort_keys=True))
        tmp.chmod(0o600)
        tmp.replace(path)
    except OSError as e:
        sys.stderr.write(f"[manifest] could not save run state: {e}\n")
    return path


def find_manifest(**match: object) -> dict | None:
    """The newest manifest whose fields equal all of `match`, if any."""
    import json

    best = None
    for path in state_dir().glob("*.json"):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        if isinstance(data, dict) and all(data.get(k) == v for k, v in match.items()):
            if best is None or str(data.get("updated_at")) > str(best.get("updated_at")):
                best = data
    return best


def prune_stale(job_id: str, lang: str, keep_if) -> list:
    """Drop cards from a language's stale-audio list that no longer apply.

    `keep_if(card_id) -> bool` decides; returns the list that remains. Stale
    means "has audio that speaks an OLD line" — a card that was re-voiced,
    removed, or has no audio at all (a blocking issue of its own) is not.
    """
    record = load_manifest(job_id)
    current = ((record.get("audio_stale") or {}).get(lang)) or []
    remaining = [c for c in current if keep_if(c)]
    if remaining != current:
        update_manifest(job_id, audio_stale={lang: remaining})
    return remaining
