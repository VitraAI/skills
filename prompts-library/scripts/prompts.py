#!/usr/bin/env python3
"""The organization's prompt library: find, use, save, edit, version and
favorite the prompts a team reuses.

  list      [--search TEXT] [--category NAME] [--favorites] [--scope private|organization|system]
  show      --prompt NAME [--fill VAR=VALUE…]      the full text; --fill completes {{variables}}
  create    --name N (--content TEXT | --content-file F) [--description] [--category NAME] [--share]
  update    --prompt NAME [--rename N] [--content…|--content-file…] [--description] [--category] [--share|--private]
  delete    --prompt NAME --confirm
  versions  --prompt NAME                          every saved version
  restore   --prompt NAME --version N              make version N the current one
  favorite / unfavorite --prompt NAME

Routes: /v1/prompts-library (+ /{id}, /{id}/versions, /{id}/favorite),
        /v1/prompt-categories

Prints JSON: { "status", "prompt" | "prompts" | "versions", … }. Prompts and
categories are named; ids never leave this script.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

PROMPTS = "/v1/prompts-library"
CATEGORIES = "/v1/prompt-categories"
VARIABLE = re.compile(r"\{\{\s*([A-Za-z0-9_.-]+)\s*\}\}")
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "") -> object:
    base, headers = _common.base_url(), _common.headers()
    data = json.dumps(body).encode() if body is not None else None
    try:
        status, payload = _http.request_json(method, base + path, headers, data,
                                             "application/json" if data else None)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error ({what}): {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"could not {what} ({status}): {_common.api_message(payload)}")
    return payload


def page(payload: object) -> list[dict]:
    data = payload.get("data") if isinstance(payload, dict) else payload
    return [r for r in data or [] if isinstance(r, dict)] if isinstance(data, list) else []


def scope(p: dict) -> str:
    return {"private": "only me", "organization": "shared", "system": "Vitra"}.get(str(p.get("visibility")), "")


def brief(p: dict) -> dict:
    out = {"name": p.get("name"), "description": p.get("description") or None, "category": p.get("category"),
           "visible_to": scope(p), "variables": p.get("variables") or None,
           "preview": p.get("contentPreview") or None, "favorite": p.get("isFavorite") or None,
           "yours": p.get("isOwner") or None}
    return {k: v for k, v in out.items() if v not in (None, "")}


def find(name: str) -> dict:
    got = page(call("GET", PROMPTS + "?" + urlencode({"search": name, "limit": 100}), what="search prompts"))
    exact = [p for p in got if str(p.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return exact[0]
    choices = [f'{p.get("name")} ({scope(p)})' for p in (exact or got)][:20]
    if not choices:
        die(_common.EXIT_API_ERROR, f'no prompt is called "{name}".', error_code="NOT_FOUND",
            ask="Which prompt? List them to see the names.")
    die(_common.EXIT_API_ERROR, f'no single prompt is called "{name}".', error_code="CHOICE_NEEDED",
        choices=choices, ask="Which prompt did you mean?")
    return {}  # unreachable


def category_id(name: str | None) -> str | None:
    if not name:
        return None
    cats = page(call("GET", CATEGORIES, what="read prompt categories"))
    for c in cats:
        if str(c.get("name") or "").strip().lower() == name.strip().lower():
            return str(c["id"])
    die(_common.EXIT_API_ERROR, f'no category is called "{name}".', error_code="CHOICE_NEEDED",
        choices=[str(c.get("name")) for c in cats], ask="Which category? Or leave it out.")
    return None


def content(args: argparse.Namespace) -> str | None:
    if args.content_file:
        path = Path(args.content_file).expanduser()
        if not path.is_file():
            die(_common.EXIT_DOWNLOAD, f"--content-file not found: {path}")
        return path.read_text(encoding="utf-8")
    return args.content


def mine(p: dict, what: str) -> None:
    if p.get("visibility") == "system" or p.get("isOwner") is False and p.get("visibility") == "private":
        die(_common.EXIT_API_ERROR, f"that prompt is read-only here; {what} a copy instead (create).")


def main() -> int:
    parser = argparse.ArgumentParser(description="Use and manage the prompt library.")
    parser.add_argument("action", choices=["list", "show", "create", "update", "delete", "versions", "restore",
                                           "favorite", "unfavorite"])
    parser.add_argument("--prompt", help="The prompt's name.")
    parser.add_argument("--search")
    parser.add_argument("--category")
    parser.add_argument("--favorites", action="store_true")
    parser.add_argument("--scope", choices=["private", "organization", "system"])
    parser.add_argument("--fill", action="append", metavar="VAR=VALUE")
    parser.add_argument("--name")
    parser.add_argument("--rename")
    parser.add_argument("--content")
    parser.add_argument("--content-file")
    parser.add_argument("--description")
    parser.add_argument("--share", action="store_true", help="Visible to the whole organization.")
    parser.add_argument("--private", action="store_true", help="Visible only to the key's owner.")
    parser.add_argument("--version", type=int)
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if args.action == "list":
        q: dict = {"limit": max(1, min(args.limit, 100)), "sort": "updatedAt", "order": "desc"}
        if args.search:
            q["search"] = args.search
        if args.category:
            q["categoryId"] = category_id(args.category)
        if args.favorites:
            q["favorite"] = "true"
        if args.scope:
            q["visibility"] = args.scope
        got = call("GET", PROMPTS + "?" + urlencode(q), what="list prompts")
        rows = page(got)
        print(json.dumps({"status": "ok", "count": got.get("total", len(rows)) if isinstance(got, dict) else len(rows),
                          "prompts": [brief(p) for p in rows]}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "create":
        text = content(args)
        if not (args.name and text):
            die(_common.EXIT_API_ERROR, "a prompt needs --name and its text (--content or --content-file).")
        body = {"name": args.name, "content": text, "visibility": "organization" if args.share else "private"}
        if args.description:
            body["description"] = args.description
        if args.category:
            body["categoryId"] = category_id(args.category)
        made = call("POST", PROMPTS, body, what="save the prompt")
        print(json.dumps({"status": "created", "prompt": brief(made if isinstance(made, dict) else {})},
                         ensure_ascii=False))
        return _common.EXIT_OK

    if not args.prompt:
        die(_common.EXIT_API_ERROR, "--prompt is required (the prompt's name).")
    found = find(args.prompt)
    pid = quote(str(found["id"]))

    if args.action == "show":
        full = call("GET", f"{PROMPTS}/{pid}", what="read the prompt")
        full = full if isinstance(full, dict) else {}
        text = str(full.get("content") or "")
        values = dict(v.split("=", 1) for v in args.fill or [] if "=" in v)
        if values:
            text = VARIABLE.sub(lambda m: values.get(m.group(1), m.group(0)), text)
        left = sorted(set(VARIABLE.findall(text)))
        out = {**brief(full), "content": text, **({"unfilled": left} if left else {})}
        out.pop("preview", None)
        print(json.dumps({"status": "ok", "prompt": out}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "update":
        mine(found, "save")
        body: dict = {}
        text = content(args)
        if text is not None:
            body["content"] = text
        if args.rename:
            body["name"] = args.rename
        if args.description is not None:
            body["description"] = args.description
        if args.category:
            body["categoryId"] = category_id(args.category)
        if args.share or args.private:
            body["visibility"] = "organization" if args.share else "private"
        if not body:
            die(_common.EXIT_API_ERROR, "nothing to change: pass the fields to update.")
        saved = call("PATCH", f"{PROMPTS}/{pid}", body, what="update the prompt")
        print(json.dumps({"status": "updated", "prompt": brief(saved if isinstance(saved, dict) else found),
                          **({"note": "saved as a new version; earlier versions can be restored"} if text is not None else {})},
                         ensure_ascii=False))
        return _common.EXIT_OK

    if args.action in ("versions", "restore"):
        rows = page(call("GET", f"{PROMPTS}/{pid}/versions?limit=100", what="read the prompt's versions"))
        if args.action == "versions":
            print(json.dumps({"status": "ok", "prompt": found.get("name"), "versions": [
                {"version": v.get("versionNumber"), "current": v.get("isActive") or None,
                 "saved": str(v.get("createdAt") or "")[:10] or None,
                 "by": (v.get("createdBy") or {}).get("name"), "preview": v.get("contentPreview")}
                for v in rows]}, ensure_ascii=False))
            return _common.EXIT_OK
        mine(found, "restore")
        hit = next((v for v in rows if v.get("versionNumber") == args.version), None)
        if not hit:
            die(_common.EXIT_API_ERROR, f"there is no version {args.version}.", error_code="CHOICE_NEEDED",
                choices=[str(v.get("versionNumber")) for v in rows], ask="Which version?")
        call("PATCH", f"{PROMPTS}/{pid}/versions/{quote(str(hit['id']))}/activate", {}, what="restore the version")
        print(json.dumps({"status": "restored", "prompt": found.get("name"), "version": args.version}))
        return _common.EXIT_OK

    if args.action in ("favorite", "unfavorite"):
        call("POST" if args.action == "favorite" else "DELETE", f"{PROMPTS}/{pid}/favorite", None,
             what=f"{args.action} the prompt")
        print(json.dumps({"status": "ok", "prompt": found.get("name"), "favorite": args.action == "favorite"},
                         ensure_ascii=False))
        return _common.EXIT_OK

    mine(found, "delete")  # delete
    if not args.confirm:
        die(_common.EXIT_API_ERROR, "deleting a prompt removes it for everyone it's shared with.",
            error_code="CONFIRM_NEEDED",
            ask=f'Delete the prompt "{found.get("name")}"? Then run the same command with --confirm.')
    call("DELETE", f"{PROMPTS}/{pid}", what="delete the prompt")
    print(json.dumps({"status": "deleted", "prompt": found.get("name")}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
