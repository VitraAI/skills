#!/usr/bin/env python3
"""The workflows this organization built in Vitra Cosmos, and what each needs.

  GET /v1/cosmos/flows

Prints JSON: { "flows": [{"name", "description", "inputs": [{"key", "label",
               "type", "required", "multiple", "description"}]}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _flows  # noqa: E402


def main() -> int:
    out = []
    for f in _flows.flows():
        inputs = [{k: v for k, v in {"key": i.get("key"), "label": i.get("label"), "type": i.get("type"),
                                     "required": i.get("required") or None, "multiple": i.get("multiple") or None,
                                     "description": i.get("description")}.items() if v is not None}
                  for i in f.get("inputSchema") or [] if isinstance(i, dict)]
        out.append({"name": f.get("name"), "description": f.get("description"), "inputs": inputs})
    print(json.dumps({"flows": out}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
