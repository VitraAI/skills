#!/usr/bin/env python3
"""See and correct a translated document line by line, then save it back.

  --translation T [--filter unverified] [--search coffee] [--page 2]   the lines
  --set "3=Bienvenue sur notre site" (repeat) [--everywhere]           correct lines
  --verify 1,4|all [--approve]                                         mark lines checked
  --sync-to-memory | --sync-from-memory                                with the translation memory
  --out ./contract-fr.docx                                             download the corrected file

Lines are numbered in document order; Office files show where each line sits
(slide, page, header). --everywhere applies a correction to every identical
line in the document.

  GET  .../document/logs/{t}/segments?page&size&filter&search
  PUT  .../document/update-phrase         { playgroundLogId, sourceText, updatePhrase, layerIndex }
  PUT  .../document/bulk-verify-phrases   { playgroundLogId, layers, verification }
  PUT  .../document/sync-to-tm | sync-from-tm   { playgroundLogId }

Prints JSON: { "status", "lines": [{"line", "source", "translation", "status", "where"?}], "total", "path"? }

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

PAGE = 50
die = _common.die


def page_of(t: str, page: int, filt: str = "all", search: str | None = None) -> tuple[list[dict], int]:
    q = {"page": page, "size": PAGE, "filter": filt, **({"search": search} if search else {})}
    got = _doc.call("GET", f"/logs/{quote(t)}/segments?{urlencode(q)}", what="read the document's lines")
    rows = got.get("data") if isinstance(got, dict) and isinstance(got.get("data"), list) else []
    total = got.get("total") if isinstance(got, dict) else None
    if total is None and isinstance(got, dict):
        total = (got.get("pagination") or {}).get("total")
    return [r for r in rows if isinstance(r, dict)], int(total or len(rows))


def line(t: str, n: int) -> dict:
    rows, total = page_of(t, (n - 1) // PAGE + 1)
    hit = next((r for r in rows if r.get("layerIndex") == n - 1), None)
    if not hit:
        die(_common.EXIT_API_ERROR, f"the document has lines 1 to {total}.")
    return hit


def show(r: dict) -> dict:
    out = {"line": int(r.get("layerIndex", 0)) + 1, "source": r.get("source"), "translation": r.get("target"),
           "status": r.get("status")}
    if isinstance(r.get("location"), dict) and r["location"].get("label"):
        out["where"] = r["location"]["label"]
    if r.get("layoutOverflow"):
        out["too_long_for_its_box"] = True
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="See and correct a translated document line by line.")
    parser.add_argument("--translation", required=True, help="From translate_document.py or documents.py list.")
    parser.add_argument("--filter", choices=["all", "unverified", "verified", "approved"], default="all")
    parser.add_argument("--search")
    parser.add_argument("--page", type=int, default=1)
    parser.add_argument("--set", action="append", default=[], metavar="N=TEXT")
    parser.add_argument("--everywhere", action="store_true", help="Apply each correction to identical lines too.")
    parser.add_argument("--verify", metavar="N,N|all")
    parser.add_argument("--approve", action="store_true", help="With --verify: mark approved, not just verified.")
    parser.add_argument("--sync-to-memory", action="store_true")
    parser.add_argument("--sync-from-memory", action="store_true")
    parser.add_argument("--out", help="Download the corrected file here.")
    args = parser.parse_args()
    t = args.translation
    out: dict = {"status": "ok"}

    changed = []
    for rule in args.set:
        n, sep, text = rule.partition("=")
        if not sep or not n.strip().isdigit() or not text.strip():
            die(_common.EXIT_API_ERROR, f'--set takes LINE=TEXT, e.g. "3=Bonjour" (got "{rule}").')
        row = line(t, int(n))
        _doc.call("PUT", "/update-phrase", {"playgroundLogId": t, "sourceText": row.get("source"),
                                            "updatePhrase": text.strip(), "layerIndex": row.get("layerIndex"),
                                            **({"propagateToDuplicates": True} if args.everywhere else {})},
                  what=f"correct line {n}")
        changed.append({"line": int(n), "before": row.get("target"), "after": text.strip()})
    if changed:
        out.update(status="corrected", changed=changed)

    if args.verify:
        if args.verify.strip().lower() == "all":
            _, total = page_of(t, 1)
            layers = list(range(total))
        else:
            try:
                layers = [int(x) - 1 for x in args.verify.split(",") if x.strip()]
            except ValueError:
                die(_common.EXIT_API_ERROR, 'lines are numbers like "1,4", or "all".')
        _doc.call("PUT", "/bulk-verify-phrases", {"playgroundLogId": t, "layers": layers,
                                                  "verification": "a" if args.approve else "v"},
                  what="mark the lines")
        out.update(status="approved" if args.approve else "verified", lines_marked=len(layers))

    if args.sync_to_memory or args.sync_from_memory:
        way = "to" if args.sync_to_memory else "from"
        _doc.call("PUT", f"/sync-{way}-tm", {"playgroundLogId": t}, what=f"sync {way} the translation memory")
        out[f"synced_{way}_memory"] = True

    if args.out:
        out["path"] = _doc.download(t, args.out)

    if not (changed or args.verify or args.sync_to_memory or args.sync_from_memory):
        rows, total = page_of(t, args.page, args.filter, args.search)
        out.update(lines=[show(r) for r in rows], total=total,
                   **({"more": f"--page {args.page + 1}"} if args.page * PAGE < total else {}))
    print(json.dumps(out, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
