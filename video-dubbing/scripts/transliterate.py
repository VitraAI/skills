#!/usr/bin/env python3
"""Turn text typed in Latin letters into the language's own script — e.g.
"namaste dosto" → "नमस्ते दोस्तो" — for writing dub lines in languages the user
can't type natively.

  GET /v1/galaxy/translate-video/language/transliterate/suggestions?text=&language=

Each word is transliterated on its own; the best guess is joined into `text`,
and words with other likely spellings list them under `alternatives`.

Prints JSON: { "text", "alternatives": {"<word>": [..]} }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
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

PATH = "/v1/galaxy/translate-video/language/transliterate/suggestions"


def main() -> int:
    parser = argparse.ArgumentParser(description="Latin letters → the language's script.")
    parser.add_argument("--text", required=True)
    parser.add_argument("--language", required=True, help="Language key, e.g. hindi_india.")
    args = parser.parse_args()
    base, headers = _common.base_url(), _common.headers()
    out, alternatives = [], {}
    for word in args.text.split():
        try:
            status, payload = _http.get_json(
                f"{base}{PATH}?{urlencode({'text': word, 'language': args.language})}", headers=headers)
        except _http.NetworkError as e:
            _common.die(_common.EXIT_API_ERROR, f"network error: {e}", retryable=True)
        if status in (401, 403):
            _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "transliterate"))
        options = (payload or {}).get("data") if isinstance(payload, dict) else None
        options = [o for o in options or [] if isinstance(o, str) and o]
        out.append(options[0] if options else word)
        if len(options) > 1:
            alternatives[word] = options[1:]
    print(json.dumps({"text": " ".join(out), **({"alternatives": alternatives} if alternatives else {})},
                     ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
