#!/usr/bin/env python3
"""The organization's cloned voices and whether each is ready to speak.

  GET /v1/galaxy/playground/voice-clone

Prints JSON: { "voices": [{"name", "provider", "voice_id", "status",
               "language", "preview_url"}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

CLONE = "/v1/galaxy/playground/voice-clone"


def main() -> int:
    try:
        status, payload = _http.get_json(_common.base_url() + CLONE, headers=_common.headers())
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error listing voices: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "list cloned voices"))
    if status != 200:
        _common.die(_common.EXIT_API_ERROR, f"could not list voices ({status}): {_common.api_message(payload)}")
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or (payload or {}).get("voices") or []
    voices = [{k: v for k, v in {
        "name": r.get("name"), "provider": r.get("provider"), "voice_id": r.get("providerVoiceId"),
        "status": r.get("status"), "language": r.get("language"), "preview_url": r.get("previewUrl"),
    }.items() if v is not None} for r in rows if isinstance(r, dict)]
    print(json.dumps({"voices": voices}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
