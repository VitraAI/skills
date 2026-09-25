#!/usr/bin/env python3
"""List the organization's Translation Memories, so the caller can pick one.

A TM carries the org's approved wording. Reusing one keeps product names, tone
and terminology identical to what they have translated before — without it every
run is translated fresh and can word the same phrase differently each time.

  GET /v1/translation-memory   (+ GET /v1/language to match language notations)

Prints one line per TM a person can read — name, languages, provider — and no
ids. Pass the chosen memory's NAME to `dub_video.py --tm-name`.

`--target-language` is the real filter. VitraTM memories are multi-source
(`supportsMultiSource: true` on /translation-memory/providers), so a TM stored
with one source language still serves any other — filtering on source would
wrongly hide it. `--source-language` therefore only constrains single-source
providers such as Phrase. Languages may be given as a name ("Spanish"), a key
("spanish_spain") or a code ("es-ES"); all three match each other.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _tm  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List Translation Memories available to this organization."
    )
    parser.add_argument("--source-language", help="Only TMs covering this source.")
    parser.add_argument("--target-language", help="Only TMs covering this target.")
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    tms = _tm.list_tms(base, headers)
    codes = _tm.load_language_codes(base, headers) if (args.source_language or args.target_language) else {}
    matching = [t for t in tms if _tm.covers(t, args.source_language, args.target_language, codes)]

    if not matching:
        if tms and (args.source_language or args.target_language):
            sys.stderr.write(
                "No Translation Memory covers that language pair "
                f"({len(tms)} exist for other pairs). Translate without one.\n"
            )
        else:
            sys.stderr.write(
                "This organization has no Translation Memories. Translate without one.\n"
            )
        return _common.EXIT_OK

    for tm in matching:
        print(_tm.describe(tm))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
