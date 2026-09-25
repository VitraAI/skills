#!/usr/bin/env python3
"""List the Translation Memory providers this organization can actually use.

  GET /v1/translation-memory/providers

Two providers exist:

  * **VitraTM** — platform-operated, always available, multi-source (one memory
    serves any source language).
  * **Phrase** — the org's own Phrase account. Only available once they have
    connected credentials, and single-source (a memory is tied to its source
    language).

Prints one line per AVAILABLE provider:  <provider>  <label>  [methods]
Unavailable providers go to stderr with the reason, so an agent never offers a
choice the caller cannot make.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
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

PROVIDERS_PATH = "/v1/translation-memory/providers"

die = _common.die


def main() -> int:
    argparse.ArgumentParser(
        description="List usable Translation Memory providers for this organization."
    ).parse_args()

    try:
        status, payload = _http.get_json(
            _common.base_url() + PROVIDERS_PATH, headers=_common.headers()
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error listing providers: {e}")

    if status in (401, 403):
        die(
            _common.EXIT_AUTH_REJECTED,
            _common.auth_error(status),
        )
    if status != 200:
        die(
            _common.EXIT_API_ERROR,
            f"could not list providers ({status}): {_common.api_message(payload)}",
        )

    rows = payload if isinstance(payload, list) else (payload or {}).get("data", [])
    available = [p for p in rows if isinstance(p, dict) and p.get("available")]
    blocked = [p for p in rows if isinstance(p, dict) and not p.get("available")]

    for p in available:
        methods = ", ".join(m.get("id", "") for m in (p.get("methods") or []))
        multi = "any source" if p.get("supportsMultiSource") else "fixed source"
        print(f"{str(p.get('provider') or '').ljust(10)} {str(p.get('label') or '').ljust(10)} [{multi}] {methods}")

    for p in blocked:
        sys.stderr.write(
            f"[unavailable] {p.get('label') or p.get('provider')} — this "
            "organization has not connected its account; do not offer it.\n"
        )

    if not available:
        die(_common.EXIT_API_ERROR, "no translation provider is available to this organization.")
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
