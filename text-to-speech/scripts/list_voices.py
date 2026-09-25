#!/usr/bin/env python3
"""Find voices for speech: the catalog plus the organization's cloned voices.

Single source: `sync-lib.sh` copies this file into the skills that use it.
Edit it here only, then run the sync.

  GET /v1/galaxy/translate-video/voice?language=&gender=&provider=&keyword=

Prints JSON: { "voices": [{"name", "provider", "voice_id", "gender",
               "cloned", "preview_url"}] } — offer a few, with their previews.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

VOICES = "/v1/galaxy/translate-video/voice"
PROVIDERS = ["elevenlabs", "cartesia", "microsoft"]


def main() -> int:
    parser = argparse.ArgumentParser(description="Find voices for speech.")
    parser.add_argument("--language", help="Language key, e.g. hindi_india (list_languages.py).")
    parser.add_argument("--gender", choices=["male", "female", "neutral"])
    parser.add_argument("--provider", choices=PROVIDERS)
    parser.add_argument("--keyword", help="Part of a voice's name or description.")
    parser.add_argument("--cloned-only", action="store_true", help="Only the organization's own cloned voices.")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    query = {"sources": "cloned" if args.cloned_only else "standard,native,cloned",
             "language": args.language, "provider": args.provider, "keyword": args.keyword,
             # Over-fetch so a gender filter still leaves enough to offer.
             "limit": min(args.limit * (4 if args.gender else 1), 200)}
    url = f"{_common.base_url()}{VOICES}?{urlencode({k: v for k, v in query.items() if v})}"
    try:
        status, payload = _http.get_json(url, headers=_common.headers())
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error listing voices: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "list voices"))
    if status != 200:
        _common.die(_common.EXIT_API_ERROR, f"could not list voices ({status}): {_common.api_message(payload)}")
    rows = payload if isinstance(payload, list) else (payload or {}).get("voices") or (payload or {}).get("data") or []
    voices = []
    for v in rows:
        if not isinstance(v, dict):
            continue
        if args.gender and str(v.get("gender") or "").lower() != args.gender:
            continue
        voices.append({k: val for k, val in {
            "name": v.get("name"), "provider": v.get("provider"),
            "voice_id": v.get("providerVoiceId") or v.get("voiceId"),
            "gender": v.get("gender"), "cloned": v.get("voiceType") == "instant-clone" or None,
            "preview_url": v.get("previewUrl"),
        }.items() if val is not None})
    print(json.dumps({"voices": voices[:args.limit]}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
