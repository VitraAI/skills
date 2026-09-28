"""What this API key may do, checked before a job starts.

Single source: `sync-lib.sh` copies this file into every skill as
`scripts/_access.py`. Edit it here only, then run the sync.

A key acts with its creator's role in ONE organization, and the organization's
plan can switch whole products off. Finding that out halfway through a paid
job wastes the user's time and credits, so each skill's `check_access.py`
lists its steps with the permissions they need and calls `check()` first.

Two sources, both what the webapp itself uses to grey out buttons:
  GET /api/auth/my-permissions        the key's effective permissions
  GET /v1/org-preference/entitlements which products the organization has

The server's own guard stays the real boundary; this only predicts it. When
the server can't answer (an older server answers API keys with "No active
organization"), the result is `unknown`: carry on, and explain any 403 when
it comes.

Stdlib only.
"""

from __future__ import annotations

import _http

PERMISSIONS_PATH = "/api/auth/my-permissions"
ENTITLEMENTS_PATH = "/v1/org-preference/entitlements"


def _get(base: str, headers: dict, path: str) -> tuple[int, object]:
    try:
        return _http.get_json(base + path, headers=headers)
    except _http.NetworkError:
        return 0, None


def _entitled(resource: str, ent: dict) -> bool | None:
    """Does the organization's plan include this resource's product?

    Galaxy resources are `<galaxy>.<feature>` (`translate_video.process_log`);
    module resources are mapped to their module by `resourceModules`. None when
    the plan doesn't say (the resource is not plan-gated).
    """
    galaxies = ent.get("galaxies") if isinstance(ent.get("galaxies"), dict) else {}
    modules = ent.get("modules") if isinstance(ent.get("modules"), dict) else {}
    mapping = ent.get("resourceModules") if isinstance(ent.get("resourceModules"), dict) else {}
    if "." in resource:
        galaxy = resource.split(".", 1)[0]
        if galaxy in galaxies:
            return bool(galaxies[galaxy])
    module = mapping.get(resource)
    if isinstance(module, str) and module in modules:
        return bool(modules[module])
    return None


def check(base: str, headers: dict, steps: list[dict]) -> dict:
    """Which of `steps` this key can run.

    `steps`: [{"step": "Start a dub", "needs": ["translate_video.process_log:create"],
               "optional": False}]

    Returns {"status": "ready" | "partial" | "blocked" | "unknown",
             "role", "can": [step names], "cannot": [{"step", "missing", "reason"}]}.
      ready    every step is allowed
      partial  only optional steps are missing (the job can run without them)
      blocked  a required step is missing
      unknown  the server could not say (older server); try, and explain 403s
    """
    status, perms = _get(base, headers, PERMISSIONS_PATH)
    granted = perms.get("permissions") if isinstance(perms, dict) else None
    role = perms.get("role") if isinstance(perms, dict) else None
    if status != 200 or not isinstance(granted, list) or (not granted and not role):
        return {"status": "unknown", "role": None, "can": [], "cannot": [],
                "note": "this server cannot report a key's permissions; the job will say if a step is not allowed"}

    have = {p for p in granted if isinstance(p, str)}
    e_status, ent = _get(base, headers, ENTITLEMENTS_PATH)
    ent = ent if e_status == 200 and isinstance(ent, dict) else {}

    can, cannot = [], []
    for s in steps:
        missing = [p for p in s["needs"] if p not in have]
        if not missing:
            can.append(s["step"])
            continue
        off_plan = [p for p in missing if _entitled(p.split(":")[0], ent) is False]
        cannot.append({
            "step": s["step"],
            "optional": bool(s.get("optional")),
            "missing": missing,
            "reason": (
                "not included in your organization's plan" if off_plan
                else "your role in this organization does not allow it"
            ),
        })

    if not cannot:
        overall = "ready"
    elif all(c["optional"] for c in cannot):
        overall = "partial"
    else:
        overall = "blocked"
    return {"status": overall, "role": role, "can": can, "cannot": cannot}


def report(base: str, headers: dict, steps: list[dict]) -> int:
    """What every skill's check_access.py does: check, explain, print one line.

    `next_action` is `collect_inputs` unless a required step is blocked.
    """
    import json
    import sys

    result = check(base, headers, steps)
    for c in result["cannot"]:
        sys.stderr.write(f"[access] cannot: {c['step']} ({c['reason']})\n")
    result["next_action"] = None if result["status"] == "blocked" else "collect_inputs"
    print(json.dumps(result))
    return 0
