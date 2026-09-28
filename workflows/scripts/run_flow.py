#!/usr/bin/env python3
"""Run one of the organization's workflows and follow it to the end, or to a
step that waits for the user's approval.

  POST /v1/cosmos/flows/{id}/run      { input, name }
  GET  /v1/cosmos/executions/{id}     until done / waiting / failed

  --input key=value   one per input (list_flows.py shows the keys);
                      a multi-value input takes comma-separated values.

Re-running the same command reconnects to the run it started.

Prints JSON: { "status": "completed" | "waiting_for_you" | "failed" |
               "cancelled", "run": "<id>", "steps": [{"step", "name",
               "status", …}], "next_action" }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import time
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _flows  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402

die = _common.die


def follow(run_id: str, max_wait: int) -> dict:
    """Wait until the run finishes or a step waits for the user."""
    names = _flows.labels()
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=5)
    last = None
    while True:
        row = _flows.run(run_id)
        status = str(row.get("status") or "").lower()
        steps = _flows.steps(row, names)
        current = next((s for s in steps if s.get("status") in ("running", "awaiting_action")), None)
        line = f"{status}: {current['name']}" if current else status
        if line != last:
            sys.stderr.write(f"[workflow] {line}\n")
            last = line
        if status in _flows.TERMINAL or status == "awaiting_action":
            break
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "the workflow is still running. Run run_status.py later; it continues "
                "on its own.", run=run_id)
        time.sleep(next(delays))
    return {"status": "waiting_for_you" if status == "awaiting_action" else status, "run": run_id,
            "steps": steps, **({"error": row.get("error")} if row.get("error") else {}),
            "next_action": "decide" if status == "awaiting_action" else None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a workflow.")
    parser.add_argument("--flow", required=True, help="The workflow's name (list_flows.py).")
    parser.add_argument("--input", action="append", default=[], metavar="KEY=VALUE")
    parser.add_argument("--name", help="A name for this run.")
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()

    flow = _flows.flow_named(args.flow)
    fields = {f.get("key"): f for f in flow.get("inputSchema") or [] if isinstance(f, dict)}
    values: dict = {}
    for item in args.input:
        key, sep, value = item.partition("=")
        if not sep or key not in fields:
            die(_common.EXIT_API_ERROR, f'"{item}" is not an input of this workflow. Inputs: '
                + (", ".join(fields) or "none"))
        values[key] = [v.strip() for v in value.split(",") if v.strip()] if fields[key].get("multiple") else value
    missing = [f.get("label") or k for k, f in fields.items() if f.get("required") and k not in values]
    if missing:
        die(_common.EXIT_API_ERROR, "this workflow needs: " + ", ".join(missing), error_code="INPUT_NEEDED",
            ask="What should I use for " + ", ".join(missing) + "?")

    key = _common.idempotency_key("flow", flow["id"], values)
    known = _state.recall("workflows", key)
    if known and str(_flows.run(known["run"]).get("status")).lower() not in _flows.TERMINAL:
        run_id = known["run"]
        sys.stderr.write("[workflow] reconnecting to the run already started\n")
    else:
        started = _flows.call("POST", f"/flows/{quote(str(flow['id']))}/run",
                              {"input": values, **({"name": args.name} if args.name else {})},
                              what="start the workflow")
        run_id = str((started or {}).get("executionId") or (started or {}).get("id"))
        _state.remember("workflows", key, {"run": run_id})
    result = follow(run_id, args.max_wait)
    print(json.dumps(result, ensure_ascii=False, default=str))
    return 0 if result["status"] in ("completed", "waiting_for_you") else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
