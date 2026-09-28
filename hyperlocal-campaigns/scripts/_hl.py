"""Hyperlocal API helpers for this skill: calls, and names → ids."""

from __future__ import annotations

from urllib.parse import quote

import _api
import _common

HL = "/v1/galaxy/hyperlocal"
die = _common.die


def call(method: str, path: str, body: dict | None = None, query: dict | None = None, what: str = "",
         quiet: bool = False) -> object:
    """One API call. `quiet`: return None on any failure instead of stopping
    (for optional reads, such as a channel the organization hasn't connected)."""
    return _api.call(method, HL + path, None if method == "GET" else body or {},
                     query={k: v for k, v in (query or {}).items() if v}, what=what, quiet=quiet)


def rows(payload: object, *keys: str) -> list[dict]:
    if isinstance(payload, list):
        return [r for r in payload if isinstance(r, dict)]
    if isinstance(payload, dict):
        for k in ("data", "items", "rows", *keys):
            v = payload.get(k)
            if isinstance(v, list):
                return [r for r in v if isinstance(r, dict)]
            if isinstance(v, dict):
                inner = rows(v, *keys)
                if inner:
                    return inner
    return []


def by_name(items: list[dict], name: str, kind: str, *fields: str) -> str:
    fields = fields or ("name",)
    hits = [i for i in items if any((str(i.get(f) or "")).casefold() == name.casefold() for f in fields)]
    if len(hits) != 1 or not hits[0].get("id"):
        names = sorted({str(i.get(f)) for i in items for f in fields[:1] if i.get(f)})
        die(_common.EXIT_API_ERROR, f'no single {kind} is called "{name}". Available: '
            + (", ".join(names[:30]) or "none"), error_code="NAME_UNKNOWN")
    return str(hits[0]["id"])


def audience(args) -> dict:
    """The broadcast audience from --group / --state / --zone / --area / --everyone."""
    groups = [by_name(rows(call("GET", "/contact-group", what="list groups"), "groups"), g, "contact group")
              for g in args.group or []]
    flt = {k: v for k, v in {"states": args.state, "zones": args.zone, "areas": args.area,
                             "excludeAreas": args.exclude_area, "groupIds": groups}.items() if v}
    if not flt and not args.everyone:
        die(_common.EXIT_API_ERROR, "who should receive it? Give --group, --state, --zone or --area "
            "(or --everyone).", error_code="AUDIENCE_NEEDED",
            ask="Who should receive it: a contact group, or contacts in which states, zones or areas?")
    return {**({"filter": flt} if flt else {}), "selectAll": True}


def add_audience_args(parser) -> None:
    parser.add_argument("--group", action="append", help="A contact group, by name (repeatable).")
    parser.add_argument("--state", action="append", help="Contacts in this state (repeatable).")
    parser.add_argument("--zone", action="append", help="Contacts in this sales zone (repeatable).")
    parser.add_argument("--area", action="append", help="Contacts in this area (repeatable).")
    parser.add_argument("--exclude-area", action="append", help="Leave out this area (repeatable).")
    parser.add_argument("--everyone", action="store_true", help="Every contact.")


def templates() -> dict[str, list[dict]]:
    out = {"creative": rows(call("GET", "/template", what="list templates"), "templates")}
    for kind, path in (("whatsapp", "/whatsapp-template"), ("facebook", "/facebook-template")):
        # The channel may not be connected for this organization.
        out[kind] = rows(call("GET", path, what=f"list {kind} templates", quiet=True), "templates")
    return out


def broadcast(bid: str) -> dict:
    row = call("GET", f"/broadcast/{quote(bid)}", what="read the campaign")
    return row.get("data") if isinstance(row, dict) and isinstance(row.get("data"), dict) else row
