#!/usr/bin/env python3
"""Translate an already-translated image into more languages.

Follow-up to `translate_image.py`: takes the `job_id` it returned and renders
the same analysed image in each new language, as a new version per language.
The analysis is reused, so only the translation itself is paid for again.

  GET  .../image-translator/{job}/translations                   languages already done
  POST .../image-translator/{job}/translate   { targetLanguage }   one per new language
  GET  .../image-translator/{job}/translations/{version}         until done

A language the image already has is not rendered again: its existing image is
returned instead (pass --again to make a fresh one).

Prints JSON: { "status": "completed" | "partial" | "failed",
               "languages": [{"target_language", "image_url", "reused"?} | {"target_language", "error"}] }

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
import _images  # noqa: E402
import translate_image as ti  # noqa: E402


def done_languages(job_id: str) -> dict[str, str]:
    """Language (lower-case) → the latest finished image for it."""
    out: dict[str, str] = {}
    for row in reversed(_images.versions(job_id)):  # oldest first, so the newest per language wins
        lang = str(row.get("targetLanguage") or "").strip().lower()
        url = row.get("translatedImageUrl") or row.get("imageUrl")
        if lang and url and str(row.get("status") or "").lower() in ti.TRANSLATE_DONE:
            out[lang] = url
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate an already-translated image into more languages.")
    parser.add_argument("--job-id", required=True, help="The job_id translate_image.py returned.")
    parser.add_argument("--target-language", action="append", required=True, metavar="LANGUAGE",
                        help="A language to add, e.g. 'German' (repeat for several).")
    parser.add_argument("--again", action="store_true", help="Render languages the image already has again.")
    parser.add_argument("--poll-interval", type=int, default=ti.DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=ti.DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    have = {} if args.again else done_languages(args.job_id)
    results = []
    for lang in dict.fromkeys(args.target_language):
        if lang.strip().lower() in have:
            results.append({"target_language": lang, "image_url": have[lang.strip().lower()], "reused": True})
            continue
        version_id = ti.start_translation(base, headers, args.job_id, lang)
        sys.stderr.write(f"[translate] {lang} started\n")
        row = ti.poll(base, headers, ti.VERSION_PATH.format(job_id=args.job_id, version_id=version_id),
                      ti.TRANSLATE_DONE, f"translate {lang}", args.poll_interval, args.max_wait)
        url = row.get("translatedImageUrl") or row.get("imageUrl")
        results.append({"target_language": row.get("targetLanguage") or lang, "image_url": url} if url
                       else {"target_language": lang, "error": "finished without an image"})
    good = [r for r in results if r.get("image_url")]
    status = "completed" if len(good) == len(results) else ("partial" if good else "failed")
    print(json.dumps({"status": status, "languages": results}, ensure_ascii=False))
    return _common.EXIT_OK if status == "completed" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
