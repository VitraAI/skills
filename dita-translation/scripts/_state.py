"""What this machine started, so a re-run reconnects instead of paying twice.

Single source: `sync-lib.sh` copies this file into the skills that use it.
Edit it here only, then run the sync.

Some Vitra jobs have no server-side deduplication. Each script records the
job it started under a key made from what it was asked to do (the file's hash,
the languages, the memory); running the same command again finds that job and
waits for it rather than starting another. Stored as JSON under
`$VITRA_STATE_DIR` (default `~/.vitra/state`).
"""

from __future__ import annotations

import json
import os
from pathlib import Path


def _file(kind: str) -> Path:
    root = Path(os.environ.get("VITRA_STATE_DIR") or Path.home() / ".vitra" / "state")
    return root / f"{kind}.json"


def _load(kind: str) -> dict:
    try:
        data = json.loads(_file(kind).read_text())
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def recall(kind: str, key: str) -> dict | None:
    value = _load(kind).get(key)
    return value if isinstance(value, dict) else None


def remember(kind: str, key: str, value: dict) -> None:
    """Best effort: a read-only home directory must never fail the job."""
    data = _load(kind)
    data[key] = value
    try:
        path = _file(kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=1))
        tmp.replace(path)
    except OSError:
        pass


def forget(kind: str, key: str) -> None:
    data = _load(kind)
    if data.pop(key, None) is not None:
        try:
            _file(kind).write_text(json.dumps(data, indent=1))
        except OSError:
            pass
