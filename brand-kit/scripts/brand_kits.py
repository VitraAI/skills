#!/usr/bin/env python3
"""Manage the organization's brand kits: colors, fonts, tone of voice, visual
style and logo, which Vitra's image tools apply when asked to stay on brand.

  list    [--search TEXT]                   kits by name
  show    --kit NAME                        one kit in full
  extract (--website URL | --image F… | --pdf F) [--brand-name] [--save]
                                            read a brand from its site, images or brand book
  create  --name N --source-url URL --color HEX… [fields]
  update  --kit NAME [--rename N] [fields] [--remove-logo]
  delete  --kit NAME --confirm

fields: --color HEX (repeat, up to 5; replaces the palette), --heading-font,
        --body-font, --tone, --style (repeat), --website, --logo FILE

Routes: GET/POST /v1/brand-kit, POST /v1/brand-kit/extract,
        GET/PATCH/DELETE /v1/brand-kit/{id}

Prints JSON: { "status", "kit" | "kits" | "draft", "next_action"? }. Kits are
named, never numbered by id. `extract` spends credits.

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import base64
import json
import re
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

KITS = "/v1/brand-kit"
LOGO_TYPES = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".svg": "image/svg+xml"}
IMAGE_TYPES = {**LOGO_TYPES, ".webp": "image/webp", ".gif": "image/gif"}
LOGO_MAX = 2 * 1024 * 1024
UPLOAD_MAX = 18 * 1024 * 1024  # the API takes JSON bodies up to 25 MB, base64 included
HEX = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})$")
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "", timeout: float = 60) -> object:
    base, headers = _common.base_url(), _common.headers()
    try:
        data = json.dumps(body).encode() if body is not None else None
        status, payload = _http.request_json(method, base + KITS + path, headers, data,
                                             "application/json" if data else None, timeout=timeout)
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


def present(kit: dict, full: bool = False) -> dict:
    tone = kit.get("toneOfVoice") or ""
    out = {"name": kit.get("name"), "colors": kit.get("primaryColors") or [],
           "heading_font": kit.get("headingFont") or None, "body_font": kit.get("bodyFont") or None,
           "tone": tone if full or len(tone) <= 160 else tone[:157].rstrip() + "…",
           "styles": kit.get("visualStyles") or [], "website": kit.get("website") or None,
           "has_logo": bool(kit.get("logoUrl"))}
    if full and kit.get("logoUrl"):
        out["logo_url"] = kit["logoUrl"]
    return {k: v for k, v in out.items() if v not in (None, "", []) or k == "has_logo"}


def find(name: str) -> dict:
    """The kit called `name`; asks when it matches several or none."""
    payload = call("GET", "?" + urlencode({"search": name, "limit": 100}), what="list brand kits")
    rows = [r for r in (payload.get("rows") if isinstance(payload, dict) else None) or [] if isinstance(r, dict)]
    exact = [r for r in rows if str(r.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return exact[0]
    choices = sorted({str(r.get("name")) for r in (exact or rows)})
    if not choices:
        die(_common.EXIT_API_ERROR, f'no brand kit is called "{name}".', error_code="KIT_NOT_FOUND",
            ask="Which brand kit? Run `brand_kits.py list` to see them.")
    die(_common.EXIT_API_ERROR, f'no kit is called exactly "{name}".', error_code="KIT_CHOICE_NEEDED",
        choices=choices, ask="Which of these kits did you mean?")
    return {}  # unreachable


def encoded(path_str: str, types: dict, cap: int, what: str) -> dict:
    path = Path(path_str).expanduser()
    if not path.is_file():
        die(_common.EXIT_DOWNLOAD, f"{what} not found: {path}")
    mime = types.get(path.suffix.lower())
    if not mime:
        die(_common.EXIT_API_ERROR, f"{what} must be one of: {', '.join(sorted(types))}.")
    if path.stat().st_size > cap:
        die(_common.EXIT_API_ERROR, f"{what} is over {cap // (1024 * 1024)} MB.")
    return {"mimeType": mime, "data": base64.b64encode(path.read_bytes()).decode()}


def fields(args: argparse.Namespace) -> dict:
    body: dict = {}
    if args.color:
        bad = [c for c in args.color if not HEX.match(c)]
        if bad or len(args.color) > 5:
            die(_common.EXIT_API_ERROR, "colors are hex codes like #8143FD, up to 5.")
        body["primaryColors"] = args.color
    for flag, key in (("heading_font", "headingFont"), ("body_font", "bodyFont"), ("tone", "toneOfVoice"),
                      ("website", "website")):
        if getattr(args, flag) is not None:
            body[key] = getattr(args, flag)
    if args.style:
        body["visualStyles"] = args.style
    if args.logo:
        body["logo"] = encoded(args.logo, LOGO_TYPES, LOGO_MAX, "the logo")
    return body


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage brand kits.")
    parser.add_argument("action", choices=["list", "show", "extract", "create", "update", "delete"])
    parser.add_argument("--kit", help="The kit's name (show, update, delete).")
    parser.add_argument("--search")
    parser.add_argument("--name", help="create: the new kit's name.")
    parser.add_argument("--rename", help="update: a new name.")
    parser.add_argument("--source-url", help="create: where the brand comes from (its website).")
    parser.add_argument("--website")
    parser.add_argument("--image", action="append", help="extract: a brand image (repeat, up to 6).")
    parser.add_argument("--pdf", help="extract: a brand book or style guide.")
    parser.add_argument("--brand-name")
    parser.add_argument("--save", action="store_true", help="extract: save the draft as a kit.")
    parser.add_argument("--color", action="append")
    parser.add_argument("--heading-font")
    parser.add_argument("--body-font")
    parser.add_argument("--tone")
    parser.add_argument("--style", action="append")
    parser.add_argument("--logo")
    parser.add_argument("--remove-logo", action="store_true")
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    if args.action == "list":
        query = "?" + urlencode({"limit": 100, **({"search": args.search} if args.search else {})})
        payload = call("GET", query, what="list brand kits")
        rows = (payload.get("rows") if isinstance(payload, dict) else None) or []
        print(json.dumps({"status": "ok", "count": payload.get("count", len(rows)),
                          "kits": [present(r) for r in rows if isinstance(r, dict)]}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "show":
        if not args.kit:
            die(_common.EXIT_API_ERROR, "--kit is required.")
        print(json.dumps({"status": "ok", "kit": present(find(args.kit), full=True)}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "extract":
        sources = [s for s in (args.website, args.image, args.pdf) if s]
        if len(sources) != 1:
            die(_common.EXIT_API_ERROR, "extract from one source: --website, --image (up to 6) or --pdf.")
        body: dict = {"brandName": args.brand_name} if args.brand_name else {}
        if args.website:
            url = args.website if "//" in args.website else "https://" + args.website
            body |= {"source": "url", "url": url}
        elif args.image:
            if len(args.image) > 6:
                die(_common.EXIT_API_ERROR, "up to 6 images.")
            body |= {"source": "images",
                     "images": [encoded(i, IMAGE_TYPES, UPLOAD_MAX, "an image") for i in args.image]}
        else:
            body |= {"source": "pdf", "pdf": encoded(args.pdf, {".pdf": "application/pdf"}, UPLOAD_MAX, "the PDF")}
        if len(json.dumps(body)) > 24 * 1024 * 1024:
            die(_common.EXIT_API_ERROR, "the files are too big together; send fewer or smaller images.")
        draft = call("POST", "/extract", body, what="read the brand", timeout=300)
        draft = draft.get("data") if isinstance(draft, dict) and isinstance(draft.get("data"), dict) else draft
        if not isinstance(draft, dict):
            die(_common.EXIT_API_ERROR, "Vitra returned no brand details.")
        if not args.save:
            print(json.dumps({"status": "draft", "draft": present(draft), "next_action": "confirm_and_save"},
                             ensure_ascii=False))
            return _common.EXIT_OK
        source_url = args.source_url or draft.get("website") or body.get("url")
        name = args.name or draft.get("name")
        if not source_url or not name or not draft.get("primaryColors"):
            die(_common.EXIT_API_ERROR, "the draft is missing a name, website or colors.", draft=present(draft),
                ask="What name, website and colors should the kit have? Then run `create` with them.")
        kit = call("POST", "", {k: v for k, v in {
            "name": name, "sourceUrl": source_url, "website": draft.get("website") or None,
            "toneOfVoice": draft.get("toneOfVoice") or None, "headingFont": draft.get("headingFont") or None,
            "bodyFont": draft.get("bodyFont") or None, "primaryColors": draft.get("primaryColors")[:5],
            "visualStyles": draft.get("visualStyles") or None}.items() if v}, what="save the brand kit")
        print(json.dumps({"status": "created", "kit": present(kit)}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "create":
        if not (args.name and args.source_url and args.color):
            die(_common.EXIT_API_ERROR, "a kit needs --name, --source-url (its website) and at least one --color.")
        kit = call("POST", "", {"name": args.name, "sourceUrl": args.source_url, **fields(args)},
                   what="create the brand kit")
        print(json.dumps({"status": "created", "kit": present(kit)}, ensure_ascii=False))
        return _common.EXIT_OK

    if not args.kit:
        die(_common.EXIT_API_ERROR, "--kit is required.")
    kit = find(args.kit)
    if args.action == "update":
        body = fields(args)
        if args.rename:
            body["name"] = args.rename
        if args.remove_logo:
            body["logo"] = None
        if not body:
            die(_common.EXIT_API_ERROR, "nothing to change: pass the fields to update.")
        kit = call("PATCH", "/" + quote(str(kit["id"])), body, what="update the brand kit")
        print(json.dumps({"status": "updated", "kit": present(kit)}, ensure_ascii=False))
        return _common.EXIT_OK

    if not args.confirm:  # delete
        die(_common.EXIT_API_ERROR, "deleting a kit can't be undone.", error_code="CONFIRM_NEEDED",
            ask=f'Delete the brand kit "{kit.get("name")}"? Then run the same command with --confirm.')
    call("DELETE", "/" + quote(str(kit["id"])), what="delete the brand kit")
    print(json.dumps({"status": "deleted", "kit": kit.get("name")}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
