#!/usr/bin/env python3
"""The organization's document translations: find, retry, rename, file, save.

  list    [--search contract] [--language French] [--status DONE] [--limit 10]
  retry   --translation T                              translate again what failed
  rename  --translation T --name "Contract (FR)"
  move    --translation T --folder NAME|Unassigned     a work folder
  save    --translation T [--folder "Contracts"] [--name N]   into the Drive

Routes: GET .../document/logs, POST .../logs/{t}/retry, PUT .../rename,
        PATCH .../logs/{t}/folder, POST .../logs/{t}/save-to-assets

Prints JSON. `translation` is for the next command only; show names.
Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _doc  # noqa: E402
import _drive  # noqa: E402
import _folders  # noqa: E402

die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Past document translations.")
    parser.add_argument("action", choices=["list", "retry", "rename", "move", "save"])
    parser.add_argument("--translation")
    parser.add_argument("--search")
    parser.add_argument("--language")
    parser.add_argument("--status")
    parser.add_argument("--name")
    parser.add_argument("--folder")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if args.action == "list":
        q = {"page": 1, "size": max(1, min(args.limit, 50)), "sort": "date_desc", "type": "playground",
             **({"search": args.search} if args.search else {}),
             **({"targetLanguage": args.language} if args.language else {}),
             **({"status": args.status.upper()} if args.status else {})}
        got = _doc.call("GET", f"/logs?{urlencode(q)}", what="list document translations")
        rows = got.get("data") if isinstance(got, dict) and isinstance(got.get("data"), list) else []
        print(json.dumps({"status": "ok", "count": got.get("totalLogs", len(rows)) if isinstance(got, dict) else 0,
                          "documents": [{"name": r.get("name"), "from": r.get("sourceLanguage"),
                                         "to": r.get("targetLanguage"), "state": str(r.get("status") or "").lower(),
                                         "memory": (r.get("PlaygroundLogTm") or {}).get("name"),
                                         "created": str(r.get("createdAt") or "")[:10],
                                         "translation": r.get("id")} for r in rows if isinstance(r, dict)]},
                         ensure_ascii=False))
        return _common.EXIT_OK

    if not args.translation:
        die(_common.EXIT_API_ERROR, "--translation is required (from translate_document.py or documents.py list).")
    t = args.translation
    if args.action == "retry":
        _doc.call("POST", f"/logs/{quote(t)}/retry", {}, what="retry the translation")
        print(json.dumps({"status": "retrying"}))
    elif args.action == "rename":
        if not args.name:
            die(_common.EXIT_API_ERROR, "--name is required.")
        _doc.call("PUT", "/rename", {"playgroundLogId": t, "name": args.name}, what="rename the translation")
        print(json.dumps({"status": "renamed", "name": args.name}, ensure_ascii=False))
    elif args.action == "move":
        if not args.folder:
            die(_common.EXIT_API_ERROR, "--folder is required (a folder name, or Unassigned).")
        print(json.dumps(_folders.move(f"{_doc.DOC}/logs/{quote(t)}/folder", args.folder), ensure_ascii=False))
    else:  # save
        print(json.dumps(_drive.save(f"{_doc.DOC}/logs/{quote(t)}/save-to-assets", args.folder, args.name,
                                     what="save the translation to the Drive"), ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
