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

import sys
from urllib.parse import urlencode

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
    engine = tm.get("engine") if provider == "vitratm" else None
    label = f"[{provider} · {engine}]" if engine else f"[{provider}]" if provider else ""
    return "  ".join(x for x in (tm.get("name") or "(unnamed)", pair, label) if x)


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


def create_tm(
    base: str,
    headers: dict,
    name: str,
    source_language: str,
    target_languages: list[str],
    context: str | None,
    engine: str | None = None,
    provider: str = "vitratm",
) -> tuple[str | None, str | None]:
    """Create a memory the way the webapp does. Returns (id, None) or (None, reason).

    A VitraTM memory needs `context`: one sentence on who it is for (client or
    product, audience). The server sends it to the model with every translation
    through the memory, so it comes from the user, never invented. `engine` is
    `gemini` (default; follows the style guide) or `azure` (ignores it).
    """
    body: dict = {
        "name": name,
        "sourceLanguage": source_language,
        "targetLanguages": target_languages,
        "tmMode": "create",
        "provider": provider,
    }
    if provider == "vitratm":
        body["context"] = (context or "").strip()
        if engine:
            body["engine"] = engine
    try:
        status, payload = _http.post_json(base + TM_PATH, headers, body)
    except _http.NetworkError as e:
        return None, f"network error: {e}"
    if status in (401, 403):
        return None, "this key is not allowed to create translation memories"
    tm_id = payload.get("id") if isinstance(payload, dict) else None
    if status not in (200, 201) or not tm_id:
        return None, f"{status}: {_common.api_message(payload)}"
    return str(tm_id), None


def find_or_create(
    base: str,
    headers: dict,
    name: str,
    source_language: str,
    target_languages: list[str],
    provider: str = "vitratm",
    context: str | None = None,
    engine: str | None = None,
) -> tuple[str | None, str | None]:
    """The memory called exactly `name`, created if it doesn't exist yet.

    Returns (id, None) or (None, reason); the caller decides whether a missing
    memory is fatal. A create that races another run (409) finds the winner.
    """
    def named() -> str | None:
        try:
            status, payload = _http.get_json(f"{base}{TM_PATH}?{urlencode({'search': name})}", headers=headers)
        except _http.NetworkError:
            return None
        hits = [t for t in rows_of(payload) if isinstance(t, dict) and t.get("name") == name and t.get("id")]
        return str(hits[0]["id"]) if status == 200 and hits else None

    found = named()
    if found:
        sys.stderr.write(f"[tm] reusing “{name}”\n")
        return found, None
    tm_id, reason = create_tm(base, headers, name, source_language, target_languages, context, engine, provider)
    if not tm_id and reason and reason.startswith("409"):
        tm_id = named()
        reason = None if tm_id else reason
    if tm_id:
        sys.stderr.write(f"[tm] created “{name}”\n")
    return tm_id, reason


def resolve(base: str, headers: dict, name: str) -> dict:
    """The full row of the memory called `name` (see resolve_by_name)."""
    tm_id = resolve_by_name(base, headers, name)
    return next(t for t in list_tms(base, headers) if str(t.get("id")) == tm_id)


def choose(base: str, headers: dict, target: str | None, name: str | None = None) -> dict:
    """The memory to use: the one named, else the only one covering `target`.

    Several that fit → stops with TM_CHOICE_NEEDED and their names (the user
    picks: the wrong one writes the wrong wording into a shared memory). None
    → stops with TM_NEEDED. Never guesses.
    """
    if name:
        tm = resolve(base, headers, name)
        if target and not covers(tm, None, target, load_language_codes(base, headers)):
            _common.die(_common.EXIT_API_ERROR,
                        f'"{tm.get("name")}" does not translate into {target}. It covers: '
                        f'{", ".join(targets_of(tm)) or "none"}.', error_code="TM_LANGUAGE_MISMATCH")
        return tm
    codes = load_language_codes(base, headers)
    fits = [t for t in list_tms(base, headers) if t.get("id") and covers(t, None, target, codes)]
    if len(fits) == 1:
        return fits[0]
    if fits:
        _common.die(_common.EXIT_API_ERROR,
                    "several translation memories fit; the user must choose one.",
                    error_code="TM_CHOICE_NEEDED",
                    ask="Which translation memory should this use?",
                    choices=[describe(t) for t in fits])
    _common.die(_common.EXIT_API_ERROR,
                f"no translation memory covers {target or 'this language'} yet.",
                error_code="TM_NEEDED",
                ask="There's no translation memory for this language yet. Create one? If so: "
                    "who is it for (the client or product, and the audience)?")
    return {}  # unreachable


def target_in(tm: dict, wanted: str, base: str, headers: dict) -> str:
    """The memory's own spelling of a requested target language."""
    codes = load_language_codes(base, headers)
    for t in targets_of(tm):
        if norm(t) == norm(wanted) or same_language(t, wanted, codes):
            return t
    _common.die(_common.EXIT_API_ERROR,
                f'"{tm.get("name")}" does not translate into {wanted}. It covers: '
                f'{", ".join(targets_of(tm)) or "none"}.', error_code="TM_LANGUAGE_MISMATCH")
    return ""  # unreachable
