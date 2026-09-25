#!/usr/bin/env python3
"""The private record of each dub this machine has worked on — what was
uploaded, the voice choices, languages added, revisions, stale cards, exports —
so any command (or a new session) can pick a run up without repeating paid
work or re-asking the caller.

  list                    every run on record, newest first
  show     --job-id X     the full record of one run
  validate --job-id X     compare the record with the server now; report drift
                          (languages added elsewhere, transcript edited since,
                          run failed) and what to do next
  forget   --job-id X     delete the local record (the dub itself is untouched)

Records live in ~/.vitra/video-dubbing/runs/ (VITRA_DUB_STATE_DIR to
override), readable only by this user. No API key and no signed links are
ever written there.

Required env for `validate`: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

STATUS_PATH = "/v1/galaxy/translate-video/process-log/{job_id}/status"

die = _common.die

# Where a run goes next, from the stage its record last reached.
NEXT_BY_STAGE = {
    "published": "dub_video",       # re-run: it reconciles to the same run
    "awaiting_voices": "resume_dub",
    "generating": "resume_dub",     # re-run: it picks the run up
    "review_ready": "inspect_process",
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Show, validate or forget local run records.")
    parser.add_argument("command", choices=["list", "show", "validate", "forget"])
    parser.add_argument("--job-id")
    args = parser.parse_args()

    if args.command == "list":
        runs = []
        for path in _common.state_dir().glob("*.json"):
            try:
                data = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            runs.append({
                "job_id": data.get("job_id"),
                "name": data.get("run_name"),
                "stage": data.get("stage"),
                "source_language": data.get("source_language"),
                "target_languages": sorted(set((data.get("target_languages") or []) + list((data.get("languages") or {}).keys()))),
                "updated_at": data.get("updated_at"),
            })
        runs.sort(key=lambda r: str(r["updated_at"]), reverse=True)
        print(json.dumps({"status": "ok", "runs": runs}))
        return _common.EXIT_OK

    if not args.job_id:
        die(_common.EXIT_API_ERROR, f"{args.command} needs --job-id")
    record = _common.load_manifest(args.job_id)
    path = _common.manifest_path(args.job_id)

    if args.command == "forget":
        existed = path.exists()
        if existed:
            path.unlink()
        print(json.dumps({"status": "forgotten" if existed else "unknown", "job_id": args.job_id}))
        return _common.EXIT_OK

    if not record:
        die(_common.EXIT_API_ERROR, f"no local record for {args.job_id}.", error_code="NO_RECORD")

    if args.command == "show":
        print(json.dumps({"status": "ok", "checkpoint": str(path), "record": record}))
        return _common.EXIT_OK

    # validate
    base = _common.base_url()
    headers = _common.headers()
    try:
        status, row = _http.get_json(base + STATUS_PATH.format(job_id=args.job_id), headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the dub: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this dub"))
    if status == 404:
        die(_common.EXIT_API_ERROR, "the server has no such dub (deleted, or another organization's key).",
            error_code="NOT_FOUND")
    if status != 200:
        die(_common.EXIT_API_ERROR, f"could not read the dub ({status}): {_common.api_message(row)}")

    import _cards

    _, revision = _cards.read_editor(base, headers, args.job_id)
    drift = []
    server_langs = set(row.get("targetLanguages") or [])
    known_langs = set(record.get("target_languages") or []) | set((record.get("languages") or {}).keys())
    if server_langs - known_langs:
        drift.append({"what": "languages added elsewhere", "languages": sorted(server_langs - known_langs)})
    if record.get("revision") is not None and revision is not None and revision != record["revision"]:
        drift.append({"what": "transcript edited since this record", "from": record["revision"], "to": revision})
    state = str(row.get("status") or "").lower()
    if state in ("failed", "cancelled"):
        drift.append({"what": f"run {state}", "error": row.get("errorMessage")})

    if state == "failed":
        next_action = "retry_dub"
    elif row.get("awaitingHumanValidation"):
        next_action = "resume_dub"
    elif state == "completed":
        next_action = "inspect_process"
    else:
        next_action = NEXT_BY_STAGE.get(str(record.get("stage")), "inspect_process")

    print(json.dumps({
        "status": "ok" if not drift else "drift",
        "job_id": args.job_id,
        "stage": record.get("stage"),
        "server_status": state,
        "revision": revision,
        "drift": drift,
        "next_action": next_action,
        "checkpoint": str(path),
    }))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
