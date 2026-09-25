#!/usr/bin/env python3
"""Check text, an image, audio or a video against one or more markets' rules
(and for unsafe content) before it goes out.

  POST /v1/galaxy/quality-control/classification/classify-text | classify-upload |
       classify-audio | classify-video
  GET  .../classification/jobs/{id}         until it settles
  GET  .../classification/decisions/{id}    the verdict per market

Prints JSON:
  { "status": "checked", "verdict": "APPROVED" | "REVIEW" | "BLOCKED", "score",
    "markets": [{"market", "verdict", "score", "concerns": [{"title",
    "severity", "why", "level": "fails" | "caution" | "note"}]}],
    "unsafe": {...} | null, "fixable": bool, "check": "<id for fix_image.py>",
    "next_action" }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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
import _http  # noqa: E402
import list_markets  # noqa: E402

QC = "/v1/galaxy/quality-control/classification"
KINDS = {  # extension → (route, limit in MB)
    **{e: ("classify-upload", 32) for e in (".png", ".jpg", ".jpeg", ".webp", ".gif")},
    **{e: ("classify-audio", 128) for e in (".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac")},
    **{e: ("classify-video", 512) for e in (".mp4", ".mov", ".webm", ".mkv", ".avi")},
}
MAX_TEXT = 20_000
die = _common.die


def concerns_of(region: dict) -> list[dict]:
    """The webapp's reading: a rule under 100 is a concern (under 50 fails,
    under 80 a caution); findings beyond the rules are always listed."""
    out = []
    for r in (region.get("per_rule") or []) + (region.get("additional_findings") or []):
        score = r.get("score")
        if not isinstance(score, (int, float)) or score >= 100:
            continue
        out.append({"title": r.get("title"), "severity": r.get("severity"), "why": r.get("rationale"),
                    "level": "fails" if score < 50 else "caution" if score < 80 else "note"})
    return sorted(out, key=lambda c: ["fails", "caution", "note"].index(c["level"]))


def main() -> int:
    parser = argparse.ArgumentParser(description="Check content against market rules.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--text", help="The text to check.")
    src.add_argument("--file", help="An image, audio or video file.")
    parser.add_argument("--market", action="append", required=True, help="A market name (list_markets.py).")
    parser.add_argument("--scope", choices=["video", "audio", "both"], help="Video only: frames, sound or both.")
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()

    base, headers = _common.base_url(), _common.headers()
    known = list_markets.regions(base, headers)
    ids = []
    for name in args.market:
        hit = next((r for r in known if (r.get("name") or "").casefold() == name.casefold()), None)
        if not hit:
            die(_common.EXIT_API_ERROR, f'no market is called "{name}". Available: '
                + (", ".join(r.get("name") or "" for r in known) or "none"), error_code="MARKET_UNKNOWN")
        ids.append(str(hit["id"]))

    try:
        if args.text is not None:
            if len(args.text) > MAX_TEXT:
                die(_common.EXIT_API_ERROR, f"text checks take up to {MAX_TEXT} characters.")
            status, payload = _http.post_json(f"{base}{QC}/classify-text", headers,
                                              {"text": args.text, "regionIds": ids})
        else:
            path = Path(args.file).expanduser()
            if not path.is_file():
                die(_common.EXIT_DOWNLOAD, f"--file not found: {path}")
            route, limit = KINDS.get(path.suffix.lower(), (None, 0))
            if not route:
                die(_common.EXIT_API_ERROR, "checks take images, audio or video: " + ", ".join(sorted(KINDS)))
            if path.stat().st_size > limit * 1024 * 1024:
                die(_common.EXIT_API_ERROR, f"that file is over the {limit} MB limit for its kind.")
            fields = {"regionIds": json.dumps(ids), **({"scope": args.scope} if args.scope else {})}
            status, payload = _http.post_multipart_json(f"{base}{QC}/{route}", headers, "file", path, fields)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error starting the check: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "check content"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    job = (payload or {}).get("jobId") if isinstance(payload, dict) else None
    if status not in (200, 201) or not job:
        die(_common.EXIT_API_ERROR, f"the check did not start ({status}): {_common.api_message(payload)}")

    deadline = time.monotonic() + args.max_wait
    delays = _http.poll_delays(first=3)
    last = None
    while True:
        status, row = _http.get_json(f"{base}{QC}/jobs/{quote(job)}", headers=headers)
        state = str((row or {}).get("status") or "").upper() if isinstance(row, dict) else ""
        stage = (row or {}).get("stage") if isinstance(row, dict) else None
        if (state, stage) != last:
            sys.stderr.write(f"[check] {(stage or state).lower()}\n")
            last = (state, stage)
        if state in ("SUCCEEDED", "FAILED"):
            break
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "the check is still running; it continues on its own.")
        time.sleep(next(delays))
    if state == "FAILED":
        die(_common.EXIT_API_ERROR, f"the check failed: {row.get('error') or 'unknown error'}", retryable=True)

    decision = ((row.get("result") or {}).get("decisionId"))
    status, detail = _http.get_json(f"{base}{QC}/decisions/{quote(str(decision))}", headers=headers)
    if status != 200 or not isinstance(detail, dict):
        die(_common.EXIT_API_ERROR, f"could not read the verdict ({status}).")
    detail = detail.get("data") if isinstance(detail.get("data"), dict) else detail
    markets = [{"market": r.get("region_name"), "verdict": r.get("verdict"),
                "score": round(r["region_score"]) if isinstance(r.get("region_score"), (int, float)) else None,
                "concerns": concerns_of(r)} for r in detail.get("regions") or []]
    fixable = detail.get("modality") == "image" and any((m["score"] or 100) < 100 for m in markets)
    print(json.dumps({
        "status": "checked", "verdict": detail.get("verdict"),
        "score": detail.get("overallScore"), "markets": markets,
        "unsafe": detail.get("nsfw"), "fixable": fixable,
        "check": decision if fixable else None,
        "next_action": "fix_image" if fixable else None,
    }, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
