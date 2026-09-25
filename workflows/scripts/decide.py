#!/usr/bin/env python3
"""Record the user's decision at a step waiting for approval — theirs, never
the agent's — then follow the run on. Rejecting ends the run. --cancel stops
a run altogether.

  POST /v1/cosmos/executions/{run}/nodes/{step}/approve | reject
  POST /v1/cosmos/executions/{run}/cancel

Required: --confirm (the user decided this, in this conversation).

Prints what run_flow.py prints, after the decision.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _flows  # noqa: E402
import run_flow  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Approve, reject or cancel.")
    parser.add_argument("--run", required=True)
    act = parser.add_mutually_exclusive_group(required=True)
    act.add_argument("--approve", type=int, metavar="STEP", help="The waiting step's number.")
    act.add_argument("--reject", type=int, metavar="STEP")
    act.add_argument("--cancel", action="store_true", help="Stop the whole run.")
    parser.add_argument("--reason", help="With --reject: why.")
    parser.add_argument("--confirm", action="store_true", help="The user made this decision.")
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()
    if not args.confirm:
        _common.die(_common.EXIT_API_ERROR, "only the user decides this; ask them, then add --confirm.",
                    error_code="CONFIRMATION_NEEDED", ask="Approve this step, or reject it?")
    run_id = quote(args.run)
    if args.cancel:
        _flows.call("POST", f"/executions/{run_id}/cancel", {}, what="cancel the run")
        print(json.dumps({"status": "cancelled", "run": args.run}))
        return 0
    number = args.approve or args.reject
    row = _flows.run(args.run)
    nodes = row.get("nodes") or []
    if not 1 <= number <= len(nodes) or nodes[number - 1].get("status") != "awaiting_action":
        _common.die(_common.EXIT_API_ERROR, f"step {number} isn't waiting for a decision.")
    node_id = quote(str(nodes[number - 1].get("nodeId")))
    decision = "approve" if args.approve else "reject"
    _flows.call("POST", f"/executions/{run_id}/nodes/{node_id}/{decision}",
                {"reason": args.reason} if args.reject and args.reason else {}, what=f"{decision} the step")
    print(json.dumps(run_flow.follow(args.run, args.max_wait), ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
