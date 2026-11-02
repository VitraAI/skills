"""Field names other tools use -> the field Vitra has for them.

One table for spreadsheet headers, TBX data categories and MultiTerm field
names, so "Part of speech", "POS", "partOfSpeech" and "Word class" all land in
the same place whatever the file was.
"""

from __future__ import annotations

from _model import header_key

# field -> spellings, compared after header_key() and with spaces removed.
_ALIASES: dict[str, list[str]] = {
    "concept_id": ["id", "concept id", "entry id", "conceptid", "entryid", "concept", "entry",
                   "termentry id", "record id", "entry number", "concept number", "uid", "guid",
                   "entry no", "concept no"],
    "language": ["language", "lang", "locale", "language code", "locale code", "xml lang"],
    "term": ["term", "terms", "term text", "entry term", "word", "keyword", "expression"],
    "domain": ["domain", "subject", "subject field", "subjectfield", "category", "field",
               "subject area", "area", "industry", "product", "product line", "client"],
    "subdomains": ["subdomain", "sub domain", "subdomains", "subcategory", "sub category",
                   "sub subject"],
    "definition": ["definition", "def", "meaning", "explanation", "description", "desc",
                   "gloss"],
    "concept_note": ["concept note", "entry note", "entry comment", "concept comment"],
    "note": ["note", "notes", "comment", "comments", "remark", "remarks", "term note",
             "translator note", "translator comment", "information", "info", "explanatory note"],
    "url": ["url", "link", "uri", "source url", "web link", "image", "xref", "graphic",
            "external cross reference"],
    "status": ["status", "term status", "approval", "approval status", "workflow status",
               "state", "review status", "entry status", "administrative status",
               "normative authorization", "usage status", "x status", "termstatus"],
    "forbidden": ["forbidden", "deprecated", "do not use", "prohibited", "not allowed",
                  "blacklisted", "banned", "forbidden term", "is forbidden"],
    "preferred": ["preferred", "preferred term", "recommended", "is preferred"],
    "case_sensitive": ["case sensitive", "case sensitivity", "match case", "case",
                       "x casesensitive", "casesensitive"],
    "exact_match": ["exact match", "whole word", "exact", "x exactmatch", "exactmatch"],
    "usage": ["usage", "usage note", "context", "example", "sample", "example sentence",
              "usage example", "context sentence", "contexts"],
    "short_form": ["short form", "shortform", "x shortform", "short translation"],
    "term_type": ["term type", "termtype", "type"],
    "part_of_speech": ["part of speech", "pos", "word class", "grammatical category",
                       "partofspeech", "grammar", "word type"],
    "gender": ["gender", "grammatical gender", "grammaticalgender"],
    "number": ["number", "grammatical number", "grammaticalnumber"],
    "dnt": ["dnt", "do not translate", "donottranslate", "untranslatable", "no translate",
            "not translatable", "keep in english", "keep as is", "keep untranslated",
            "non translatable", "nontranslatable", "x dnt", "notranslate"],
    "translatable": ["translatable", "translate", "is translatable"],
    "synonyms": ["synonym", "synonyms", "alternative", "alternatives", "alt term", "variants",
                 "alternative terms", "other terms"],
    "tags": ["tags", "tag", "labels", "label", "keywords"],
}

# Bookkeeping no Vitra field holds: counted in the report, never imported.
_ADMIN_PREFIXES = ("created", "creation", "creator", "modified", "modification", "changed",
                   "change ", "updated", "update ", "last ", "author", "user", "date", "time",
                   "timestamp", "transac", "stamp", "cr date", "ch date", "cr by", "ch by",
                   "reported by", "requested by", "owner", "responsibility", "approved by",
                   "reviewed by", "version", "revision", "project id", "job id", "row id",
                   "entry created", "entry modified", "term created", "term modified",
                   "entry last", "term last")

_LOOKUP: dict[str, str] = {}
for _field, _names in _ALIASES.items():
    for _n in _names:
        _LOOKUP[_n] = _field
        _LOOKUP[_n.replace(" ", "")] = _field


def field_of(name: str) -> str | None:
    """The Vitra field a column / data category name means, or None."""
    k = header_key(name)
    if not k:
        return None
    return _LOOKUP.get(k) or _LOOKUP.get(k.replace(" ", ""))


def is_admin(name: str) -> bool:
    k = header_key(name)
    return bool(k) and (k.startswith(_ADMIN_PREFIXES) or k in ("by", "id user", "modifier"))


# Words a wide sheet uses as headers that are also language codes ("ID" is
# Indonesian, "No" Norwegian): never read as a language column.
NOT_LANGUAGE_HEADERS = {"id", "no", "nr", "as", "or", "to", "an", "am", "be", "is", "me", "my",
                        "so", "ha", "on", "by", "at", "in", "if", "na", "ok", "st", "uid",
                        "num", "key", "ref", "pos", "new", "old", "yes", "all", "any", "def",
                        "eg", "ie"}
