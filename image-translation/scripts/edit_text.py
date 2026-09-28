#!/usr/bin/env python3
"""See and correct the text in a translated image, line by line.

  --job-id J [--language French]                     list the lines (numbered)
  --set "3=Promo" (repeat) [--keep 5,6]              re-render with those lines changed
  --verify 1,2|all                                   mark lines checked
  --sync-to-memory                                   save the verified lines to the memory

A change re-renders the image as a new version (the analysis is reused, and
only lines not given are machine-translated again); --keep leaves a line in
its original language, e.g. a brand name.

  GET  .../image-translator/{job}/translations                         the versions
  POST .../image-translator/{job}/translate  {targetLanguage, overrides}  --set/--keep
  PUT  .../{job}/translations/{version}/bulk-region-status  {regionIds, status: "v"}
  PUT  .../{job}/translations/{version}/sync-to-tm

Prints JSON: { "status", "language", "lines": [{"line", "source", "translation", "status"?}],
               "image_url"? }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _api  # noqa: E402
import _common  # noqa: E402
import _images  # noqa: E402
import translate_image as ti  # noqa: E402

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="See and correct the text in a translated image.")
    parser.add_argument("--job-id", required=True, help="The job_id translate_image.py returned.")
    parser.add_argument("--language", help="Which language's image (default: the newest).")
    parser.add_argument("--set", action="append", default=[], metavar="N=TEXT", help='e.g. "3=Promo" (repeat).')
    parser.add_argument("--keep", metavar="N,N", help="Lines to leave in their original language.")
    parser.add_argument("--verify", metavar="N,N|all", help="Mark these lines as checked.")
    parser.add_argument("--sync-to-memory", action="store_true", help="Save verified lines to the memory.")
    parser.add_argument("--poll-interval", type=int, default=ti.DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=ti.DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    job = args.job_id
    version = _images.latest(job, args.language)
    language = version.get("targetLanguage") or args.language
    vid = quote(str(version.get("id") or version.get("translationVersionId")))
    out: dict = {"status": "ok", "language": language}

    if args.set or args.keep:
        overrides: dict = {}
        for rule in args.set:
            n, sep, text = rule.partition("=")
            if not sep or not n.strip().isdigit() or not text.strip():
                die(_common.EXIT_API_ERROR, f'--set takes LINE=TEXT, e.g. "3=Promo" (got "{rule}").')
            overrides[_images.region_ids(version, n)[0]] = {"editedText": text.strip()}
        for rid in _images.region_ids(version, args.keep) if args.keep else []:
            overrides[rid] = {"action": "keep"}
        started = ti.start_translation_with(_common.base_url(), _common.headers(), job,
                                            {"targetLanguage": language, "overrides": overrides})
        version = ti.poll(_common.base_url(), _common.headers(), ti.VERSION_PATH.format(job_id=job, version_id=started),
                          ti.TRANSLATE_DONE, "re-render", args.poll_interval, args.max_wait)
        version = {**version, **_images.full(job, str(started))}
        vid = quote(str(started))
        out["status"] = "edited"
        out["image_url"] = version.get("translatedImageUrl") or version.get("imageUrl")

    if args.verify:
        ids = _images.region_ids(version, args.verify)
        _api.call("PUT", f"{_images.IT}/{quote(job)}/translations/{vid}/bulk-region-status",
                  {"regionIds": ids, "status": "v"}, what="mark the lines as checked")
        out["status"] = "verified" if out["status"] == "ok" else out["status"]
        version = _images.full(job, vid)

    if args.sync_to_memory:
        _api.call("PUT", f"{_images.IT}/{quote(job)}/translations/{vid}/sync-to-tm", {},
                  what="save the lines to the translation memory")
        out["synced_to_memory"] = True

    out["lines"] = _images.lines(version)
    print(json.dumps(out, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
