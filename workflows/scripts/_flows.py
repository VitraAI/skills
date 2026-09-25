"""Cosmos API helpers for this skill: calls, flow lookup, readable steps."""

from __future__ import annotations

from urllib.parse import quote

import _common
import _http

COSMOS = "/v1/cosmos"
TERMINAL = {"completed", "failed", "cancelled"}
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "") -> object:
    base, headers = _common.base_url(), _common.headers()
    try:
        if method == "GET":
            status, payload = _http.get_json(base + COSMOS + path, headers=headers)
        else:
            status, payload = _http.post_json(base + COSMOS + path, headers, body or {})
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error ({what}): {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not {what} ({status}): {_common.api_message(payload)}")
    return payload


def flows() -> list[dict]:
    rows = call("GET", "/flows", what="list workflows")
    rows = rows if isinstance(rows, list) else (rows or {}).get("data") or (rows or {}).get("flows") or []
    return [f for f in rows if isinstance(f, dict) and f.get("id")]


def flow_named(name: str) -> dict:
    hits = [f for f in flows() if (f.get("name") or "").casefold() == name.casefold()]
    if len(hits) != 1:
        die(_common.EXIT_API_ERROR, f'no single workflow is called "{name}". Available: '
            + (", ".join(f.get("name") or "" for f in flows()) or "none"), error_code="NAME_UNKNOWN")
    return hits[0]


def labels() -> dict[str, str]:
    palette = call("GET", "/node-types", what="read step types")
    return {t.get("key"): t.get("label") for t in (palette or {}).get("nodeTypes") or [] if isinstance(t, dict)}


def run(run_id: str) -> dict:
    return call("GET", f"/executions/{quote(run_id)}", what="read the run")


def steps(run_row: dict, names: dict[str, str]) -> list[dict]:
    """The run's steps in order, numbered from 1, as people read them."""
    out = []
    for n, node in enumerate(run_row.get("nodes") or [], 1):
        if not isinstance(node, dict):
            continue
        control = node.get("control") or {}
        if control.get("kind") in ("start", "end"):
            continue  # bookends, not steps
        cfg = control.get("config") or {}
        out.append({k: v for k, v in {
            "step": n, "name": names.get(node.get("nodeTypeKey")) or node.get("nodeTypeKey"),
            "status": node.get("status"), "error": node.get("error"),
            "waiting_for_you": node.get("status") == "awaiting_action" or None,
            "asks": (cfg.get("instructions") or cfg.get("message") or cfg.get("description"))
            if node.get("status") == "awaiting_action" else None,
            "output": node.get("output") if node.get("status") in ("succeeded", "completed") else None,
        }.items() if v is not None})
    return out
