"""Quality reports (AIQE): wait for one, and read its worst lines.

Single source: `sync-lib.sh` copies this file into the skills that use it.
Edit it here only, then run the sync.
"""

from __future__ import annotations

import sys
import time
from typing import Callable
from urllib.parse import quote, urlencode

import _common
import _http

REPORTS = "/v1/aiqe/reports"
# queued, running, then succeeded / partial (some lines failed) / failed / cancelled.
DONE = ("succeeded", "partial")
TERMINAL = ("succeeded", "partial", "failed", "cancelled")
die = _common.die


def _unwrap(payload: object) -> dict:
    if isinstance(payload, dict) and isinstance(payload.get("data"), dict):
        return payload["data"]
    return payload if isinstance(payload, dict) else {}


def wait(base: str, headers: dict, report: dict, max_wait: int) -> dict:
    """Poll a report until it settles; dies unless it produced scores."""
    rid = str(report.get("id"))
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=5)
    while str(report.get("status") or "").lower() not in TERMINAL:
        if time.monotonic() >= deadline:
            die(_common.EXIT_TIMEOUT, "the report is still running; it continues on its own — try again later.")
        p = report.get("progress") or {}
        sys.stderr.write(f"[quality] {p.get('done', 0)}/{p.get('total', '?')} lines\n")
        time.sleep(next(delays))
        status, payload = _http.get_json(f"{base}{REPORTS}/{quote(rid)}", headers=headers)
        if status == 200:
            report = _unwrap(payload)
    if str(report.get("status")).lower() not in DONE:
        die(_common.EXIT_API_ERROR, f"the report {report.get('status')}: {report.get('error') or ''}".strip(),
            retryable=True)
    return report


def worst_lines(base: str, headers: dict, rid: str, show: int,
                label: Callable[[str], dict] | None = None) -> tuple[int, list[dict]]:
    """(lines with errors, the `show` lowest-scoring of them, as people read them).

    A segment's `key` is what the run sent: a line number for documents and
    text; `label` turns any other key into names (a DITA map: file + phrase).
    """
    q = urlencode({"hasErrors": "true", "sort": "score", "limit": min(max(show, 1), 200)})
    status, payload = _http.get_json(f"{base}{REPORTS}/{quote(rid)}/segments?{q}", headers=headers)
    rows: list = []
    if status == 200:  # {segments, nextCursor}, possibly under `data`, or a bare list
        for candidate in (payload, (payload or {}).get("data") if isinstance(payload, dict) else None):
            if isinstance(candidate, list):
                rows = candidate
                break
            if isinstance(candidate, dict) and isinstance(candidate.get("segments"), list):
                rows = candidate["segments"]
                break
    bad = sorted((s for s in rows if isinstance(s, dict) and s.get("errors")),
                 key=lambda s: s.get("score") if isinstance(s.get("score"), (int, float)) else 101)
    out = []
    for s in bad[:max(0, show)]:
        key = str(s.get("key") or "")
        where = label(key) if label else {"line": int(key) if key.isdigit() else s.get("index")}
        out.append({
            **where,
            "source": s.get("sourceText"), "translation": s.get("targetText"), "score": s.get("score"),
            "errors": [{"severity": e.get("severity"), "category": e.get("category"),
                        "why": e.get("explanation"), "suggestion": e.get("suggestion")}
                       for e in s.get("errors") or [] if isinstance(e, dict)],
            **({"better": s["correctedTarget"]} if s.get("correctedTarget") else {}),
        })
    return len(bad), out


def summary(report: dict) -> dict:
    card = report.get("scorecard") or {}
    return {"score": card.get("score"), "band": card.get("band"), "passed": card.get("passed"),
            "lines_with_errors": card.get("segmentsWithErrors"),
            **({"note": "some lines could not be scored"} if str(report.get("status")).lower() == "partial" else {})}
