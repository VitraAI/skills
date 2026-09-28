#!/usr/bin/env python3
"""Creative templates (the personalized image each contact gets) and the
WhatsApp / Facebook message templates a campaign can use. WhatsApp templates
must be approved by Meta before they can send.

Prints JSON: { "creative": [names], "whatsapp": [{"name", "status"}],
               "facebook": [{"name", "status"}] }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _hl  # noqa: E402


def main() -> int:
    t = _hl.templates()
    print(json.dumps({
        "creative": [r.get("title") or r.get("name") for r in t["creative"]],
        "whatsapp": [{"name": r.get("name") or r.get("title"), "status": r.get("status")} for r in t["whatsapp"]],
        "facebook": [{"name": r.get("name") or r.get("title"), "status": r.get("status")} for r in t["facebook"]],
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
