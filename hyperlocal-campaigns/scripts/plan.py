#!/usr/bin/env python3
"""What a campaign would reach and cost — nothing is created or sent.

  POST /v1/galaxy/hyperlocal/broadcast/estimate

Prints JSON: { "contacts": N, "credits": {"creatives", "sending", "total"} }

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
    parser = argparse.ArgumentParser(description="Estimate a campaign's reach and cost.")
    parser.add_argument("--template", required=True, help="Creative template, by name (templates.py).")
    parser.add_argument("--channel", action="append", required=True, choices=["whatsapp", "facebook"])
    _hl.add_audience_args(parser)
    args = parser.parse_args()
    template = _hl.by_name(_hl.templates()["creative"], args.template, "creative template", "title", "name")
    est = _hl.call("POST", "/broadcast/estimate", {"fk_templateId": template, "channels": args.channel,
                                                    **_hl.audience(args)}, what="estimate the campaign")
    est = est.get("data") if isinstance(est, dict) and isinstance(est.get("data"), dict) else est
    print(json.dumps({"contacts": est.get("contacts"),
                      "credits": {"creatives": est.get("generation"), "sending": est.get("send"),
                                  "total": est.get("total")}}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
