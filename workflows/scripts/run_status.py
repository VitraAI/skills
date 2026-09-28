#!/usr/bin/env python3
"""Where a workflow run is, step by step (outputs of finished steps included).

Prints JSON: { "status", "steps": [{"step", "name", "status", …}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _flows  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="A workflow run's status.")
    parser.add_argument("--run", required=True)
    args = parser.parse_args()
    row = _flows.run(args.run)
    status = str(row.get("status") or "").lower()
    print(json.dumps({"status": "waiting_for_you" if status == "awaiting_action" else status,
                      "workflow": row.get("flowName"), "steps": _flows.steps(row, _flows.labels()),
                      **({"error": row.get("error")} if row.get("error") else {})},
                     ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
