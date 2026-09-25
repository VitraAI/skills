"""Translation Memory helpers shared by the skills that translate.

Single source: `sync-lib.sh` copies this file into image-translation and
video-dubbing as `scripts/_tm.py`. Edit it here only, then run the sync.

Two jobs:

- Decide whether a TM covers a language pair. TMs store languages in three
  notations: names ("Spanish"), keys ("spanish_spain") and BCP-47 codes
  ("es-ES"). The API's language list holds all three for every language, so
  both sides are reduced to the base code ("es") before comparing, instead of
  guessing from the first letters (which matched Tagalog to Tamil and missed
  Spanish vs es-ES).
- Let callers choose a TM by its NAME. People pick memories by name; the id is
  an internal handle the scripts resolve themselves and never print.

Stdlib only.
"""

from __future__ import annotations

import _common
import _http

TM_PATH = "/v1/translation-memory"
LANGUAGE_PATH = "/v1/language"

# Providers that accept ANY source language. The API reports this as
# `supportsMultiSource` on GET /translation-memory/providers: vitratm is true,
# phrase is false. Filtering a multi-source TM by its stored `sourceLanguage`
# hides memories that would in fact serve the request.
MULTI_SOURCE_PROVIDERS = {"vitratm"}


def rows_of(payload: object) -> list:
    """List routes vary: a bare array, or `{rows}` / `{data}` / `{items}`."""
    rows = payload
    for _ in range(2):
        if isinstance(rows, list):
            return rows
        if not isinstance(rows, dict):
            return []
        for key in ("rows", "data", "items", "memories"):
            if key in rows:
                rows = rows[key]
                break
        else:
            return []
    return rows if isinstance(rows, list) else []


def targets_of(tm: dict) -> list[str]:
    raw = tm.get("targetLanguages") or tm.get("targetLanguage") or []
    return [raw] if isinstance(raw, str) else [t for t in raw if isinstance(t, str)]


def norm(value: str | None) -> str:
    """Case and separator insensitive: `hi-IN` → `hi_in`."""
    return (value or "").strip().lower().replace("-", "_")


def load_language_codes(base: str, headers: dict) -> dict[str, str]:
    """Every spelling the API uses for a language → its base code.

    `spanish`, `Spanish`, `spanish_spain`, `Spanish (Spain)`, `es`, `es-ES` all
    map to `es`. Empty if the list can't be fetched; matching then falls back
    to comparing codes directly.
    """
    try:
        status, payload = _http.get_json(base + LANGUAGE_PATH, headers=headers)
    except _http.NetworkError:
        return {}
    if status != 200:
        return {}
    codes: dict[str, str] = {}
    for row in rows_of(payload):
        if not isinstance(row, dict):
            continue
        code = row.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        base_code = norm(code).split("_")[0]
        for spelling in (row.get("name"), row.get("label"), code):
            if isinstance(spelling, str) and spelling.strip():
                codes.setdefault(norm(spelling), base_code)
    return codes


def base_code(value: str, codes: dict[str, str]) -> str:
    """`Spanish (Spain)` / `spanish_spain` / `es-ES` → `es`."""
    v = norm(value)
    if v in codes:
        return codes[v]
    head = v.split("_")[0]
    if head in codes:
        return codes[head]
    # An unlisted BCP-47 tag still has its language first: `xx-YY` → `xx`.
    return head if 2 <= len(head) <= 3 else v


def same_language(a: str, b: str, codes: dict[str, str]) -> bool:
    if not norm(a) or not norm(b):
        return False
    return base_code(a, codes) == base_code(b, codes)


def covers(tm: dict, source: str | None, target: str | None, codes: dict[str, str]) -> bool:
    """Can this TM serve the requested pair?

    TARGET is the real constraint. SOURCE only constrains single-source
    providers (Phrase): a VitraTM memory takes any source.
    """
    if source and norm(tm.get("provider")) not in MULTI_SOURCE_PROVIDERS:
        src = tm.get("sourceLanguage") or ""
        # `auto` accepts anything.
        if norm(src) not in ("", "auto") and not same_language(src, source, codes):
            return False
    if target and not any(same_language(t, target, codes) for t in targets_of(tm)):
        return False
    return True


def describe(tm: dict) -> str:
    """One line a person can read: name, languages, provider. No ids."""
    targets = targets_of(tm)
    shown = ", ".join(targets[:6]) + (f" (+{len(targets) - 6} more)" if len(targets) > 6 else "")
    pair = f"{tm.get('sourceLanguage') or 'any source'} → {shown}" if targets else ""
    provider = tm.get("provider") or ""
    return "  ".join(x for x in (tm.get("name") or "(unnamed)", pair, f"[{provider}]" if provider else "") if x)


def list_tms(base: str, headers: dict) -> list[dict]:
    """Every TM the key's organization can use. Dies on auth or API errors."""
    try:
        status, payload = _http.get_json(base + TM_PATH, headers=headers)
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error listing translation memories: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status != 200:
        _common.die(
            _common.EXIT_API_ERROR,
            f"could not list translation memories ({status}): {_common.api_message(payload)}",
        )
    return [t for t in rows_of(payload) if isinstance(t, dict)]


def resolve_by_name(base: str, headers: dict, name: str) -> str:
    """The id of the TM called `name` (case-insensitive, exact). Dies with the
    available names if there is no such TM, or if the name is ambiguous."""
    tms = list_tms(base, headers)
    wanted = name.strip().casefold()
    hits = [t for t in tms if (t.get("name") or "").strip().casefold() == wanted]
    if len(hits) == 1 and hits[0].get("id"):
        return str(hits[0]["id"])
    if len(hits) > 1:
        _common.die(
            _common.EXIT_API_ERROR,
            f'{len(hits)} translation memories are called "{name}". Ask the caller which one: '
            + "; ".join(describe(t) for t in hits),
        )
    names = ", ".join(sorted({(t.get("name") or "").strip() for t in tms if t.get("name")})) or "none"
    _common.die(
        _common.EXIT_API_ERROR,
        f'No translation memory is called "{name}". Available: {names}. '
        "Run list_tms.py and use one of those names exactly.",
    )
    return ""  # unreachable: die() exits
