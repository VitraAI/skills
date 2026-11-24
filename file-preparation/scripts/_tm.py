"""Translation memory rows -> VitraTM import sheets.

The sheet is VitraTM's own long layout (vitra-tm segment/io/sheet.ts):
Source language | Source text | Target language | Target text | Status.
A unit is (source language, normalized source text), exactly as VitraTM keys
it, so one source with several translations into one language is decided
here, with every alternative listed in the report, instead of the import
silently keeping whichever came last.
"""

from __future__ import annotations

import os
import re

import _lang
from _model import LIMIT_BYTES, LIMIT_TM_UNITS, TM_STATUSES, Log, TmRow, claim, norm_key
from _xlsx import MAX_CELL_CHARS, has_invalid_xml, strip_invalid_xml, write_xlsx

HEADER = ["Source language", "Source text", "Target language", "Target text", "Status"]


class Resolver:
    """Language tags -> Vitra codes, each distinct tag resolved (and reported) once."""

    def __init__(self, overrides: dict[str, str]):
        self.overrides = overrides
        self.cache: dict[str, str | None] = {}
        self.seen: dict[str, str | None] = {}

    def __call__(self, raw: str) -> str | None:
        raw = (raw or "").strip()
        if raw not in self.cache:
            self.cache[raw] = _lang.resolve(raw, self.overrides) if raw else None
            self.seen[raw] = self.cache[raw]
        return self.cache[raw]


def _date_key(d: str) -> str:
    return re.sub(r"\D", "", d or "")[:14].ljust(14, "0")


# How one source with several translations into a language is decided.
CONFLICT_RULES = {
    "frequent": "the most used translation (ties: the most recently changed, then the last in the file)",
    "latest": "the most recently changed translation (ties: the most used, then the last in the file)",
    "last": "the translation that comes last in the file",
}
_RANK = {
    "frequent": lambda c: (c["count"], c["date"], c["last"]),
    "latest": lambda c: (c["date"], c["count"], c["last"]),
    "last": lambda c: (c["last"],),
}

_SPECIAL_SPACE = {"\u00a0": "[NBSP]", "\u202f": "[NNBSP]", "\u2009": "[THIN SPACE]", "\u2007": "[FIGURE SPACE]",
                  "\t": "[TAB]", "\n": "[LINE BREAK]", "\u3000": "[IDEOGRAPHIC SPACE]", "\u200b": "[ZERO WIDTH SPACE]"}


def show_spaces(text: str) -> str:
    """Text with its special spaces made visible, for the report."""
    return "".join(_SPECIAL_SPACE.get(ch, ch) for ch in text)


def _when(dk: str) -> str:
    d = dk.rstrip("0")
    if not d:
        return ""
    dk = dk.ljust(14, "0")
    return f"{dk[0:4]}-{dk[4:6]}-{dk[6:8]} {dk[8:10]}:{dk[10:12]}"


def build_units(rows: list[TmRow], file: str, log: Log, resolve: Resolver, default_status: str | None,
                rule: str = "frequent"):
    """Validated, de-duplicated units in first-seen order:
    [(source language, source text, [(target language, text, status)])]."""
    units: dict[tuple[str, str], dict] = {}
    order = 0
    for r in rows:
        order += 1
        s_code, t_code = resolve(r.src_lang), resolve(r.tgt_lang)
        src, tgt = r.src_text, r.tgt_text
        if not src.strip():
            log.exclude(file, r.where, "TM", r.tgt_lang, "", tgt[:300], "No source text")
            continue
        if not tgt.strip():
            log.exclude(file, r.where, "TM", r.tgt_lang, src[:300], "", "No translation (empty target)")
            continue
        if not s_code:
            log.exclude(file, r.where, "TM", r.src_lang, src[:300], tgt[:300],
                        f"Source language '{r.src_lang}' is not in Vitra's language list" if r.src_lang
                        else "Source language missing")
            continue
        if not t_code:
            log.exclude(file, r.where, "TM", r.tgt_lang, src[:300], tgt[:300],
                        f"Target language '{r.tgt_lang}' is not in Vitra's language list" if r.tgt_lang
                        else "Target language missing")
            continue
        if s_code == t_code:
            log.exclude(file, r.where, "TM", t_code, src[:300], tgt[:300],
                        "Translation is in the source language")
            continue
        for label, text in (("Source text", src), ("Target text", tgt)):
            if has_invalid_xml(text):
                cleaned = strip_invalid_xml(text)
                log.change(file, r.where, label, repr(text[:200]), cleaned[:200],
                           "Invisible control characters removed (they cannot be stored in a file)")
        src, tgt = strip_invalid_xml(src), strip_invalid_xml(tgt)
        if len(src) > MAX_CELL_CHARS or len(tgt) > MAX_CELL_CHARS:
            log.exclude(file, r.where, "TM", t_code, src[:300], tgt[:300],
                        f"Longer than {MAX_CELL_CHARS} characters, the most a spreadsheet cell holds")
            continue
        status = r.status
        if status and status.startswith("?"):
            log.change(file, r.where, "Status", status[1:], default_status or "",
                       "Unknown status; the import default is used")
            status = None
        if status and status not in TM_STATUSES:
            status = None
        status = status or default_status
        key = (s_code, norm_key(src))
        u = units.get(key)
        if u is None:
            u = units[key] = {"src": src, "order": order, "langs": {}}
        elif src != u["src"]:
            log.change(file, r.where, "Source text", src[:300], u["src"][:300],
                       "Same source text with different spacing: merged into one entry")
            log.duplicates.append({"file": file, "language": t_code, "where": r.where,
                                   "source": show_spaces(src), "target": show_spaces(tgt),
                                   "in_vitra": "Merged into the unit whose source is " + show_spaces(u["src"])[:300]})
        cands = u["langs"].setdefault(t_code, {})
        ck = norm_key(tgt)
        c = cands.get(ck)
        if c is None:
            c = cands[ck] = {"count": 0, "text": tgt, "status": status, "date": "", "last": 0, "wheres": [],
                             "texts": set()}
        c["count"] += 1
        c["texts"].add(tgt)
        dk = _date_key(r.date)
        if dk >= c["date"]:
            c["date"], c["text"], c["status"] = dk, tgt, status or c["status"]
        c["last"] = order
        c["wheres"].append(r.where)

    out = []
    rank = _RANK.get(rule, _RANK["frequent"])
    for (s_code, _), u in sorted(units.items(), key=lambda kv: kv[1]["order"]):
        translations = []
        for t_code, cands in u["langs"].items():
            ranked = sorted(cands.values(), key=rank, reverse=True)
            keep = ranked[0]
            for c in ranked:
                if c["count"] > 1 or len(c["texts"]) > 1:
                    log.duplicates.append({
                        "file": file, "language": t_code, "where": ", ".join(c["wheres"][:5]),
                        "source": show_spaces(u["src"]), "target": show_spaces(c["text"]),
                        "in_vitra": (f"{c['count']} copies imported as one" +
                                     (" (they differ only in spacing)" if len(c["texts"]) > 1 else ""))})
            if len(ranked) > 1:
                for c in ranked:
                    kept = c is keep
                    why = rule_reason(rule, keep, ranked) if kept else _drop_why(rule, c, keep)
                    log.conflicts.append({"file": file, "language": t_code, "source": u["src"], "target": c["text"],
                                          "where": ", ".join(c["wheres"][:5]), "times": c["count"],
                                          "changed": _when(c["date"]), "kept": kept, "why": why})
                for other in ranked[1:]:
                    log.exclude(file, ", ".join(other["wheres"][:5]), "TM", t_code, u["src"][:300],
                                other["text"][:300], "Another translation of the same source was kept "
                                f"({_drop_why(rule, other, keep)})")
            translations.append((t_code, keep["text"], keep["status"] or ""))
        out.append((s_code, u["src"], translations))
    return out


def _drop_why(rule: str, c: dict, keep: dict) -> str:
    if rule == "last":
        return "earlier in the file"
    order = [("count", "used less often"), ("date", "older")]
    if rule == "latest":
        order.reverse()
    for k, why in order:
        if c[k] < keep[k]:
            return why
    return "earlier in the file"


def rule_reason(rule: str, keep: dict, ranked: list[dict]) -> str:
    if rule == "last":
        return "last in the file"
    if rule == "frequent":
        if keep["count"] > ranked[1]["count"]:
            return f"used most ({keep['count']} times)"
        return "tied on use, most recently changed" if keep["date"] > ranked[1]["date"] else "tied, last in the file"
    if keep["date"] > ranked[1]["date"]:
        return "most recently changed"
    return "same date, used most" if keep["count"] > ranked[1]["count"] else "tied, last in the file"


def _rows(units):
    for s_code, src, translations in units:
        for t_code, text, status in translations:
            yield [s_code, src, t_code, text, status]


def write_units(units, out_dir: str, base: str, max_units: int = LIMIT_TM_UNITS,
                max_bytes: int = LIMIT_BYTES) -> list[dict]:
    """Write ≤ max_units units and ≤ max_bytes per file; every unit's rows stay in one file."""
    chunks = [units[i:i + max_units] for i in range(0, len(units), max_units)] or [[]]
    written: list[tuple[str, list]] = []
    tmp_n = 0

    def emit(chunk):
        nonlocal tmp_n
        tmp_n += 1
        path = os.path.join(out_dir, f".{base}.tm.{tmp_n}.tmp.xlsx")
        write_xlsx(path, [("Translations", HEADER, _rows(chunk))])
        if os.path.getsize(path) > max_bytes and len(chunk) > 1:
            os.remove(path)
            half = len(chunk) // 2
            emit(chunk[:half])
            emit(chunk[half:])
            return
        written.append((path, chunk))

    for ch in chunks:
        emit(ch)
    results = []
    total = len(written)
    for i, (tmp, chunk) in enumerate(written, 1):
        suffix = f" - part {i:02d} of {total:02d}" if total > 1 else ""
        final = claim(os.path.join(out_dir, f"{base} - TM{suffix}.xlsx"))
        os.replace(tmp, final)
        langs = sorted({s for s, _, _ in chunk}), sorted({t for _, _, tr in chunk for t, _, _ in tr})
        results.append({
            "file": final,
            "import_into": "Translation memory",
            "units": len(chunk),
            "rows": sum(len(tr) for _, _, tr in chunk),
            "source_languages": langs[0],
            "target_languages": langs[1],
            "bytes": os.path.getsize(final),
        })
    return results
