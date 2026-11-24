"""Shared records, text helpers and the conversion log.

Every reader turns a client file into these records, so the rules that decide
what is kept, changed or dropped are written once (in _tm.py and _terms.py),
whatever the source tool was.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field

# What VitraTM accepts per file (vitra-tm: segment/io/types.ts,
# term-base.service.ts, glossary.service.ts) and the upload cap of 25 MB.
LIMIT_TM_UNITS = 100_000
LIMIT_TB_CONCEPTS = 5_000
LIMIT_GLOSSARY_ENTRIES = 20_000
LIMIT_BYTES = 25 * 1024 * 1024

TM_STATUSES = ("unverified", "verified", "approved")


@dataclass
class TmRow:
    """One translation of one source text."""

    src_lang: str
    src_text: str
    tgt_lang: str
    tgt_text: str
    where: str
    status: str | None = None
    date: str = ""


@dataclass
class Term:
    lang: str
    text: str
    where: str = ""
    # Vitra term fields (status, forbidden, preferred, case_sensitive, exact_match,
    # note, usage, short_form, term_type, part_of_speech, gender, number), raw values.
    fields: dict[str, str] = field(default_factory=dict)
    # (label, value) text with no field of its own: kept in the term's note.
    extra: list[tuple[str, str]] = field(default_factory=list)
    dnt: bool | None = None


@dataclass
class Concept:
    where: str
    id: str = ""
    # domain, subdomains, url, definition, concept_note
    fields: dict[str, str] = field(default_factory=dict)
    extra: list[tuple[str, str]] = field(default_factory=list)
    terms: list[Term] = field(default_factory=list)
    dnt: bool | None = None


@dataclass
class GlossaryEntry:
    where: str
    term: str
    lang: str
    description: str = ""
    translatable: bool | None = None
    case_sensitive: bool | None = None
    tags: list[str] = field(default_factory=list)
    # (language, text, note)
    translations: list[tuple[str, str, str]] = field(default_factory=list)


class Log:
    """Everything the report shows: nothing is dropped or changed without a line here."""

    def __init__(self) -> None:
        self.excluded: list[list[str]] = []  # file, where, kind, language, text, detail, reason
        self.changed: list[list[str]] = []  # file, where, what, before, after, reason
        self.not_imported: dict[tuple[str, str], list] = {}  # (file, field) -> [count, example]
        self.values: dict[tuple[str, str, str, str], int] = {}  # (file, column, before, after) -> count
        self.notes: list[str] = []
        # Data problems worth a person's eye; nothing here stops a conversion (see _checks.py).
        self.issues: list[dict] = []
        # TM: every source with several translations, every alternative and which one was kept.
        self.conflicts: list[dict] = []
        # TM: rows merged into another one (exact copies, or spacing-only differences).
        self.duplicates: list[dict] = []

    def exclude(self, file: str, where: str, kind: str, language: str, text: str,
                detail: str, reason: str) -> None:
        self.excluded.append([file, where, kind, language, text, detail, reason])

    def change(self, file: str, where: str, what: str, before: str, after: str, reason: str) -> None:
        self.changed.append([file, where, what, before, after, reason])

    def drop_field(self, file: str, name: str, example: str) -> None:
        slot = self.not_imported.setdefault((file, name), [0, ""])
        slot[0] += 1
        if not slot[1] and example:
            slot[1] = example[:200]

    def value(self, file: str, column: str, before: str, after: str) -> None:
        """A field value read as another (or kept in the note): counted, one report line per kind."""
        key = (file, column, before, after)
        self.values[key] = self.values.get(key, 0) + 1

    def note(self, text: str) -> None:
        if text not in self.notes:
            self.notes.append(text)

    def issue(self, file: str, where: str, asset: str, check: str, item: str, detail: str,
              in_vitra: str, level: str = "check") -> None:
        """A data problem in the client's file. level: "check" (a person should look) or "info"."""
        self.issues.append({"file": file, "where": where, "asset": asset, "check": check, "item": item,
                            "detail": detail, "in_vitra": in_vitra, "level": level})


# Output paths this run has written: a second input with the same name gets " (2)"
# instead of overwriting, while a re-run into the same folder replaces its old files.
CLAIMED: set[str] = set()


def claim(path: str) -> str:
    import os
    stem, ext = os.path.splitext(path)
    n, out = 1, path
    while out in CLAIMED:
        n += 1
        out = f"{stem} ({n}){ext}"
    CLAIMED.add(out)
    return out


_WS = re.compile(r"\s+")


def norm_key(text: str) -> str:
    """VitraTM's identity normalization (hash.util normalizeText): NFC, trim, one space."""
    return _WS.sub(" ", unicodedata.normalize("NFC", text).strip())


def fold_key(text: str) -> str:
    return norm_key(text).casefold()


def clean_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


_TRUE = {"yes", "y", "true", "1", "x", "oui", "ja", "si", "sí", "da", "✓", "✔"}
_FALSE = {"no", "n", "false", "0", "non", "nein", "-"}


def to_bool(value: str | None) -> bool | None:
    if value is None:
        return None
    s = str(value).strip().lower()
    if not s:
        return None
    if s in _TRUE:
        return True
    if s in _FALSE:
        return False
    return None


_CAMEL = re.compile(r"(?<=[a-z])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")


def header_key(h: str) -> str:
    h = re.sub(r"‹[^›]*›", " ", str(h))  # MultiTerm "Usage Note ‹Usage Status›"
    # camelCase and PascalCase headers ("SourceTermDefinition", "partOfSpeech") read as words.
    h = _CAMEL.sub(" ", h).lower()
    return _WS.sub(" ", re.sub(r"[_\-./:()\[\]<>]+", " ", h)).strip()


# What tools and clients write in a cell that has no value. Never imported as text.
# A term cell is held to the short list: "NA" or "TBD" can be real terms.
_PLACEHOLDER_TERMS = {"n/a", "n.a.", "n. a.", "#n/a", "-", "--", "—", "–", "null", "?", "??"}
_PLACEHOLDER_FIELDS = _PLACEHOLDER_TERMS | {"na", "tbd", "tbc", "(none)", "(empty)", "none"}


def is_placeholder(value: str | None, term: bool = False) -> bool:
    return bool(value) and str(value).strip().lower() in (_PLACEHOLDER_TERMS if term else _PLACEHOLDER_FIELDS)
