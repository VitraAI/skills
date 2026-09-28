"""Projects and tasks: API calls and the name lookups both scripts share.

Projects and tasks store their status and priority as ids from a board
(statuses grouped NOT_STARTED / ACTIVE / DONE / CLOSED, plus priorities):
the organization's project board for projects, each project's own board for
its tasks. People pick them by name, so every id is looked up here and never
printed. People are named by their name; members are found by name or email.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote, urlencode

import _common
import _http

GROUPS = ("NOT_STARTED", "ACTIVE", "DONE", "CLOSED")
DATE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "", quiet_404: bool = False) -> object:
    base, headers = _common.base_url(), _common.headers()
    data = json.dumps(body).encode() if body is not None else None
    try:
        status, payload = _http.request_json(method, base + path, headers, data,
                                             "application/json" if data else None)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error ({what}): {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status == 404 and quiet_404:
        return None
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not {what} ({status}): {_common.api_message(payload)}")
    return payload


def rows(payload: object) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    return [r for r in data or [] if isinstance(r, dict)] if isinstance(data, list) else []


def ask_choice(kind: str, name: str, choices: list[str]) -> None:
    if not choices:
        die(_common.EXIT_API_ERROR, f'no {kind} is called "{name}".', error_code="NOT_FOUND",
            ask=f"Which {kind}? List them to see the names.")
    die(_common.EXIT_API_ERROR, f'no {kind} is called exactly "{name}".', error_code="CHOICE_NEEDED",
        choices=choices[:20], ask=f"Which {kind} did you mean?")


# ── Projects ────────────────────────────────────────────────────────────────

def find_project(name: str) -> dict:
    got = rows(call("GET", "/v1/project?" + urlencode({"keyword": name, "limit": 50}), what="list projects"))
    exact = [p for p in got if str(p.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return exact[0]
    ask_choice("project", name, sorted({str(p.get("name")) for p in (exact or got)}))
    return {}  # unreachable


def org_board() -> dict:
    """The organization's project board (one per organization)."""
    got = call("GET", "/v1/project-template", what="read the project statuses", quiet_404=True)
    boards = got if isinstance(got, list) else rows(got)
    return boards[0] if boards else {}


def task_board(project: dict) -> dict:
    got = call("GET", f"/v1/task-template/project/{quote(str(project['id']))}", what="read the task statuses",
               quiet_404=True)
    got = got.get("data") if isinstance(got, dict) and isinstance(got.get("data"), dict) else got
    return got if isinstance(got, dict) else {}


def statuses(board: dict) -> list[dict]:
    out = []
    for group in GROUPS:
        for s in (board.get("status") or {}).get(group) or []:
            if isinstance(s, dict) and s.get("id"):
                out.append({"id": str(s["id"]), "name": str(s.get("name") or ""), "group": group})
    return out


def priorities(board: dict) -> list[dict]:
    return [{"id": str(p["id"]), "name": str(p.get("name") or p["id"])}
            for p in board.get("priority") or [] if isinstance(p, dict) and p.get("id")]


def names(board: dict) -> dict:
    """What a board offers, by name: to show, and to choose from."""
    return {"statuses": [s["name"] for s in statuses(board)], "priorities": [p["name"] for p in priorities(board)]}


def id_of(options: list[dict], name: str | None, kind: str) -> str | None:
    if not name:
        return None
    for o in options:
        if o["name"].strip().lower() == name.strip().lower() or o["id"] == name:
            return o["id"]
    die(_common.EXIT_API_ERROR, f'"{name}" is not a {kind} here.', error_code="CHOICE_NEEDED",
        choices=[o["name"] for o in options], ask=f"Which {kind}?")
    return None


def name_of(options: list[dict], ident: object) -> str | None:
    return next((o["name"] for o in options if o["id"] == str(ident)), None) if ident else None


def done_group(options: list[dict], ident: object) -> bool:
    return any(o["id"] == str(ident) and o["group"] in ("DONE", "CLOSED") for o in options)


# ── People ──────────────────────────────────────────────────────────────────

def person(member: dict) -> str | None:
    """A project or task member row → the person's name."""
    user = ((member.get("orgMember") or {}).get("user") or {}) if isinstance(member, dict) else {}
    return user.get("name") or user.get("email")


def org_member(project: dict, who: str) -> dict:
    """An organization member by name or email: {id, name}."""
    q = {"organizationId": project.get("fk_orgId"), "limit": 100, "filterField": "name",
         "filterOperator": "contains", "filterValue": who}
    if "@" in who:
        q |= {"filterField": "email", "filterValue": who}
    got = call("GET", "/api/auth/organization/list-members?" + urlencode(q), what="look up organization members")
    members = [m for m in (got.get("members") if isinstance(got, dict) else None) or [] if isinstance(m, dict)]
    wanted = who.strip().lower()
    exact = [m for m in members if wanted in (str((m.get("user") or {}).get("name") or "").lower(),
                                              str((m.get("user") or {}).get("email") or "").lower())]
    if len(exact) == 1:
        return {"id": str(exact[0]["id"]), "name": exact[0]["user"].get("name") or who}
    pool = exact or members
    labels = [f'{(m.get("user") or {}).get("name")} <{(m.get("user") or {}).get("email")}>' for m in pool]
    if not pool:
        die(_common.EXIT_API_ERROR, f'nobody called "{who}" is in this organization.', error_code="NOT_FOUND",
            ask="Who did you mean? Their name or email as it is in Vitra.")
    die(_common.EXIT_API_ERROR, f'several people match "{who}".', error_code="CHOICE_NEEDED",
        choices=labels[:20], ask="Which person? Pass their email to be exact.")
    return {}  # unreachable


# ── Languages and dates ─────────────────────────────────────────────────────

_LANGS: list[dict] = []


def language_key(value: str) -> str:
    """`Hindi`, `hi-IN` or `hindi_india` → the key projects store."""
    if not _LANGS:
        _LANGS.extend(rows(call("GET", "/v1/language", what="read languages")))
    v = value.strip().lower()
    for fields in (("name",), ("label",), ("code",)):
        hits = [r for r in _LANGS if any(str(r.get(f) or "").lower() == v for f in fields)]
        if len(hits) == 1:
            return str(hits[0]["name"])
        if hits:
            break
    near = [r for r in _LANGS if v in f'{r.get("name")} {r.get("label")} {r.get("code")}'.lower()]
    die(_common.EXIT_API_ERROR, f'"{value}" matches no single language.', error_code="CHOICE_NEEDED",
        choices=[str(r.get("label") or r.get("name")) for r in (hits or near)][:20], ask="Which language?")
    return ""  # unreachable


def date(value: str | None, flag: str) -> str | None:
    if value and not DATE.match(value):
        die(_common.EXIT_API_ERROR, f"{flag} is a date like 2026-10-31.")
    return value


def day(value: object) -> str | None:
    return str(value)[:10] if value else None
