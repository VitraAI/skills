"""Subtitle lines between people and the API.

Single source: `sync-lib.sh` copies this file into the video skills. Edit it
here only, then run the sync.

A language's subtitle lines are numbered from 1 across the whole video, in
order; people and every script refer to them by that number. A line's stored
text is HTML-style markup (`<br>` = line break): `to_plain` shows it, `to_api`
escapes what someone typed (a line break stays "\\n"; the API does the rest).
"""

from __future__ import annotations

import html
import re

import _cards

_BR = re.compile(r"<br\s*/?>", re.I)
_TAG = re.compile(r"<[^>]*>")


def to_plain(markup: str | None) -> str:
    return html.unescape(_TAG.sub("", _BR.sub("\n", markup or ""))).strip()


def to_api(plain: str) -> str:
    return html.escape(str(plain).strip(), quote=False)


def numbered(cards: list, lang: str) -> list[tuple[str, dict]]:
    """[(card id, subtitle)] for a language, in line-number order."""
    out = []
    for card in cards:
        if not isinstance(card, dict):
            continue
        for sub in _cards.block(card, lang).get("subs") or []:
            if isinstance(sub, dict) and sub.get("id"):
                out.append((str(card.get("id")), sub))
    return out


def _round(x: object) -> object:
    return round(x, 2) if isinstance(x, (int, float)) else x


def subtitle_lines(cards: list, lang: str) -> list[dict]:
    """[{line, start, end, text}] as people read them."""
    out = []
    for n, (_, sub) in enumerate(numbered(cards, lang), 1):
        t = sub.get("t") if isinstance(sub.get("t"), dict) else {}
        out.append({"line": n, "start": _round(t.get("st")), "end": _round(t.get("et")),
                    "text": to_plain(sub.get("text"))})
    return out


def page(items: list, offset: int, limit: int, more_flag: str) -> dict:
    """{items, total, more?}: one page of a long list, and how to get the next."""
    limit = max(1, limit)
    out: dict = {"total": len(items), "items": items[offset:offset + limit]}
    if offset + limit < len(items):
        out["more"] = f"{more_flag} --offset {offset + limit}"
    return out
