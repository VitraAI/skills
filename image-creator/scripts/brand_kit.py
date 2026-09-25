#!/usr/bin/env python3
"""Resolve a brand kit for a domain — reusing an existing one before extracting.

Extraction costs a model call and creates a duplicate row, so this ALWAYS checks
the organization's saved kits first and only falls back to extracting when the
domain genuinely has no kit yet.

  GET  .../brand-kit                     list saved kits, match on domain/name
  POST .../brand-kit/extract             (only if no match) pull from the site
  POST .../brand-kit                     (only if --save) persist the draft

Prints JSON:
  { "resolved": "existing" | "extracted",
    "name": "...", "primary_colors": [...], "heading_font": "...",
    "body_font": "...", "tone_of_voice": "...", "visual_styles": [...],
    "prompt_fragment": "..." }

`prompt_fragment` is ready to append to a generate_image.py --prompt.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

BRAND_KIT_PATH = "/v1/brand-kit"
EXTRACT_PATH = BRAND_KIT_PATH + "/extract"

EXTRACT_TIMEOUT = 300.0

die = _common.die


def rows_of(payload: object) -> list:
    """This API answers `{ count, rows }`; others use `data`/`items`."""
    rows = payload
    for _ in range(2):
        if isinstance(rows, list):
            return rows
        if not isinstance(rows, dict):
            return []
        for key in ("rows", "data", "items"):
            if key in rows:
                rows = rows[key]
                break
        else:
            return []
    return rows if isinstance(rows, list) else []


def host_of(value: str | None) -> str:
    """Bare hostname for comparison: `https://www.Vitra.ai/x` -> `vitra.ai`."""
    if not value:
        return ""
    raw = value.strip().lower()
    if "//" not in raw:
        raw = "https://" + raw
    host = urlparse(raw).netloc or ""
    return host[4:] if host.startswith("www.") else host


def match(kits: list, domain: str, name: str | None) -> dict | None:
    """An existing kit for this domain (or, failing that, this name)."""
    target = host_of(domain)
    for kit in kits:
        if not isinstance(kit, dict):
            continue
        if target and target in {
            host_of(kit.get("website")),
            host_of(kit.get("sourceUrl")),
        }:
            return kit
    if name:
        wanted = name.strip().lower()
        for kit in kits:
            if isinstance(kit, dict) and (kit.get("name") or "").strip().lower() == wanted:
                return kit
    return None


def describe(kit: dict) -> str:
    """A prompt fragment an image model can actually act on."""
    bits = []
    colors = [c for c in (kit.get("primaryColors") or []) if c]
    if colors:
        bits.append("brand colors " + ", ".join(colors))
    styles = [s for s in (kit.get("visualStyles") or []) if s]
    if styles:
        bits.append(f"visual style: {', '.join(styles)}")
    heading, body = kit.get("headingFont"), kit.get("bodyFont")
    if heading or body:
        fonts = heading if heading == body else " / ".join(x for x in (heading, body) if x)
        bits.append(f"typography like {fonts}")
    tone = kit.get("toneOfVoice")
    if tone:
        bits.append(f"tone: {tone.rstrip('.')}")
    return ". ".join(bits) + "." if bits else ""


def present(kit: dict, resolved: str) -> dict:
    return {
        "resolved": resolved,
        "name": kit.get("name"),
        "primary_colors": kit.get("primaryColors") or [],
        "heading_font": kit.get("headingFont"),
        "body_font": kit.get("bodyFont"),
        "tone_of_voice": kit.get("toneOfVoice"),
        "visual_styles": kit.get("visualStyles") or [],
        "prompt_fragment": describe(kit),
    }


def api(method, url, headers, body=None, label="request", timeout=60.0):
    try:
        if method == "GET":
            status, payload = _http.get_json(url, headers=headers)
        else:
            status, payload = _http.post_json(url, headers, body or {}, timeout=timeout)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error on {label}: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"{label} failed ({status}): {_common.api_message(payload)}",
        )
    return payload


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Resolve a brand kit for a domain, reusing a saved one when it exists."
    )
    parser.add_argument(
        "--domain",
        required=True,
        help="Brand site, e.g. vitra.ai or https://www.vitra.ai",
    )
    parser.add_argument("--brand-name", help="Name hint, used to seed extraction.")
    parser.add_argument(
        "--save",
        action="store_true",
        help="Persist a freshly extracted kit. Ignored when an existing one matched.",
    )
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    # 1. Reuse before extracting — cheaper, and avoids duplicate rows.
    kits = rows_of(api("GET", base + BRAND_KIT_PATH, headers, label="list brand kits"))
    found = match(kits, args.domain, args.brand_name)
    if found:
        sys.stderr.write(f"[brand-kit] reusing saved kit “{found.get('name')}”\n")
        print(json.dumps(present(found, "existing")))
        return _common.EXIT_OK

    # 2. Nothing saved for this domain — extract from the live site.
    url = args.domain if "//" in args.domain else f"https://{args.domain}"
    sys.stderr.write(f"[brand-kit] no saved kit for {host_of(url)}; extracting…\n")
    body = {"source": "url", "url": url}
    if args.brand_name:
        body["brandName"] = args.brand_name
    draft = api(
        "POST", base + EXTRACT_PATH, headers, body, "extract", timeout=EXTRACT_TIMEOUT
    )
    draft = draft if isinstance(draft, dict) else {}
    draft = draft.get("data") if isinstance(draft.get("data"), dict) else draft

    if args.save:
        saved = api(
            "POST",
            base + BRAND_KIT_PATH,
            headers,
            {
                "name": draft.get("name") or args.brand_name or host_of(url),
                "sourceUrl": url,
                "website": draft.get("website") or url,
                "toneOfVoice": draft.get("toneOfVoice"),
                "headingFont": draft.get("headingFont"),
                "bodyFont": draft.get("bodyFont"),
                "primaryColors": draft.get("primaryColors") or [],
                "visualStyles": draft.get("visualStyles") or [],
            },
            "save brand kit",
        )
        saved = saved if isinstance(saved, dict) else {}
        sys.stderr.write("[brand-kit] saved\n")
        print(json.dumps(present(saved, "extracted")))
        return _common.EXIT_OK

    print(json.dumps(present(draft, "extracted")))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
