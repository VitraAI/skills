#!/usr/bin/env python3
"""Who can be reached: contact groups, the states / zones / areas contacts are
in, or contacts matching a search.

  --groups                         named groups and their size
  --places states|zones|areas [--state S]
  --contacts [--search T] [--state S] [--zone Z] [--area A] [--group G]

Prints JSON with only names and counts; never contact details beyond a name.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _hl  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Groups, places and contacts.")
    what = parser.add_mutually_exclusive_group(required=True)
    what.add_argument("--groups", action="store_true")
    what.add_argument("--places", choices=["states", "zones", "areas"])
    what.add_argument("--contacts", action="store_true")
    parser.add_argument("--search")
    parser.add_argument("--state", action="append")
    parser.add_argument("--zone", action="append")
    parser.add_argument("--area", action="append")
    parser.add_argument("--group", action="append")
    args = parser.parse_args()
    join = lambda v: ",".join(v) if v else None  # noqa: E731
    if args.groups:
        groups = _hl.rows(_hl.call("GET", "/contact-group", query={"search": args.search}, what="list groups"),
                          "groups")
        out = {"groups": [{"name": g.get("name"), "contacts": g.get("memberCount", g.get("contactCount"))}
                          for g in groups]}
    elif args.places:
        payload = _hl.call("GET", f"/contact/{args.places}", query={"states": join(args.state)},
                           what=f"list {args.places}")
        values = payload if isinstance(payload, list) else _hl.rows(payload) or (payload or {}).get("data") or []
        out = {args.places: [v if isinstance(v, str) else v.get("name") or v.get("value") for v in values]}
    else:
        groups = [_hl.by_name(_hl.rows(_hl.call("GET", "/contact-group", what="list groups"), "groups"), g,
                              "contact group") for g in args.group or []]
        payload = _hl.call("GET", "/contact", query={
            "search": args.search, "states": join(args.state), "zones": join(args.zone),
            "areas": join(args.area), "groupIds": join(groups), "limit": 10}, what="search contacts")
        found = _hl.rows(payload, "contacts")
        total = payload.get("total") or (payload.get("meta") or {}).get("total") if isinstance(payload, dict) else None
        out = {"total": total if total is not None else len(found),
               "sample": [c.get("name") or c.get("firmName") or c.get("personName") for c in found]}
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
