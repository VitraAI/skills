#!/usr/bin/env python3
"""The organization's image translations: find them, retry, file, reuse.

  list      [--search TEXT] [--language French] [--limit 10]   past images, newest first
  retry     --job-id J                                          redo whatever failed, in place
  move      --job-id J --folder NAME|Unassigned                 file it in a work folder
  template  --job-id J --language French                        send a campaign image back to Hyperlocal

Routes: GET .../image-translator/jobs/list, POST .../{job}/retry,
        PATCH .../{job}/folder, POST .../{job}/save-as-template

Prints JSON: { "status", "images": [{"name", "languages", "image_url", "memory", "job_id"}] | … }.
`job_id` is for the next command only; show the name and languages.

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlencode, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _api  # noqa: E402
import _common  # noqa: E402
import _folders  # noqa: E402
import _images  # noqa: E402

die = _common.die


def summary(job: dict) -> dict:
    done = [v for v in job.get("translationVersions") or [] if str(v.get("status") or "").lower() in _images.DONE]
    name = job.get("name") or Path(urlparse(str(job.get("sourceUrl") or "")).path).name or "image"
    out = {"name": name, "languages": sorted({str(v.get("targetLanguage")) for v in done if v.get("targetLanguage")}),
           "image_url": (done[0].get("translatedImageUrl") if done else None), "memory": job.get("tmName"),
           "created": str(job.get("createdAt") or "")[:10] or None, "job_id": job.get("id")}
    if job.get("source") == "hyper-local":
        out["from_campaign"] = True
    return {k: v for k, v in out.items() if v not in (None, [], "")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Past image translations: list, retry, move, template.")
    parser.add_argument("action", choices=["list", "retry", "move", "template"])
    parser.add_argument("--job-id")
    parser.add_argument("--search")
    parser.add_argument("--language")
    parser.add_argument("--folder")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if args.action == "list":
        q = {"page": 1, "size": max(1, min(args.limit, 50)), "sort": "date_desc",
             **({"search": args.search} if args.search else {}),
             **({"targetLanguage": args.language} if args.language else {})}
        got = _api.call("GET", f"{_images.IT}/jobs/list?{urlencode(q)}", what="list image translations")
        rows = _api.rows(got)
        print(json.dumps({"status": "ok", "count": got.get("total", len(rows)) if isinstance(got, dict) else len(rows),
                          "images": [summary(r) for r in rows]}, ensure_ascii=False))
        return _common.EXIT_OK

    if not args.job_id:
        die(_common.EXIT_API_ERROR, "--job-id is required (from translate_image.py or images.py list).")
    job = quote(args.job_id)

    if args.action == "retry":
        _api.call("POST", f"{_images.IT}/{job}/retry", {}, what="retry the image", timeout=300)
        print(json.dumps({"status": "retrying", "next_action": "images.py list, or edit_text.py to see the result"}))
    elif args.action == "move":
        if not args.folder:
            die(_common.EXIT_API_ERROR, "--folder is required (a folder name, or Unassigned).")
        print(json.dumps(_folders.move(f"{_images.IT}/{job}/folder", args.folder), ensure_ascii=False))
    else:  # template
        version = _images.latest(args.job_id, args.language)
        url = version.get("translatedImageUrl")
        _api.call("POST", f"{_images.IT}/{job}/save-as-template",
                  {"targetLanguage": version.get("targetLanguage"), "outputUrl": url},
                  what="save the image as a campaign template")
        print(json.dumps({"status": "saved_as_template", "language": version.get("targetLanguage")},
                         ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
