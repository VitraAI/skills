"""Terminology -> VitraTM term base or glossary import sheets.

Routing: a terminology file whose every concept is do-not-translate becomes a
glossary (entries with Translatable = no, which VitraTM enforces). Anything
else becomes a term base. `--as` overrides both ways.

Term base sheet = vitra-tm term-base/io/sheet.ts, one row per term.
Glossary sheet  = vitra-tm glossary/io/sheet.ts, one row per entry, a column
per language; an unknown column fails that import, so extra data goes in
Description or a "<code> note" column, never in a column of its own.
"""

from __future__ import annotations

import html
import os
import re
from collections import Counter

from _model import (LIMIT_BYTES, LIMIT_GLOSSARY_ENTRIES, LIMIT_TB_CONCEPTS, Concept, GlossaryEntry, Log,
                    Term, claim, fold_key, norm_key, to_bool)
from _tm import Resolver
from _xlsx import MAX_CELL_CHARS, strip_invalid_xml, write_xlsx

TB_HEADER = ["Concept ID", "Domain", "Subdomains", "URL", "Definition", "Concept note", "Language", "Term",
             "Status", "Forbidden", "Preferred", "Case sensitive", "Exact match", "Note", "Usage",
             "Short form", "Term type", "Part of speech", "Gender", "Number"]
GL_FIXED = ["Term", "Language", "Description", "Translatable", "Case sensitive", "Tags"]

# ------------------------------------------------------------------ value maps

_STATUS = {
    "approved": "approved", "final": "approved", "validated": "approved", "released": "approved",
    "confirmed": "approved", "accepted": "approved", "admitted": "approved", "signed off": "approved",
    "admittedterm admn sts": "approved", "approvedsignoff": "approved", "valid": "approved",
    "standardized": "approved", "standard": "approved", "reviewed": "approved", "active": "approved",
    "new": "new", "draft": "new", "proposed": "new", "pending": "new", "candidate": "new",
    "unreviewed": "new", "in progress": "new", "to review": "new", "for review": "new",
    "not reviewed": "new", "suggested": "new", "provisional": "new", "under review": "new",
    "rejected": "rejected", "refused": "rejected", "declined": "rejected", "invalid": "rejected",
}
_FORBIDDEN = {"forbidden", "deprecated", "do not use", "dont use", "obsolete", "superseded", "prohibited",
              "not allowed", "banned", "avoid", "deprecatedterm admn sts", "supersededterm admn sts",
              "notrecommended", "not recommended", "legacy", "blacklisted", "forbidden term"}
_PREFERRED = {"preferred", "preferredterm admn sts", "recommended", "preferred term"}
_TERM_TYPE = {
    "full form": "full_form", "fullform": "full_form", "full": "full_form", "main entry term": "full_form",
    "short form": "short_form", "shortform": "short_form", "acronym": "acronym",
    "abbreviation": "abbreviation", "abbr": "abbreviation", "abbreviated form": "abbreviation",
    "phrase": "phrase", "phraseological unit": "phrase", "phraseologicalunit": "phrase",
    "set phrase": "phrase", "variant": "variant", "spelling variant": "variant", "other": "other",
}
_POS = {"noun": "noun", "n": "noun", "nn": "noun", "substantive": "noun", "verb": "verb", "v": "verb",
        "vb": "verb", "adjective": "adjective", "adj": "adjective", "a": "adjective", "adverb": "adverb",
        "adv": "adverb", "other": "other"}
_GENDER = {"masculine": "masculine", "m": "masculine", "masc": "masculine", "male": "masculine",
           "feminine": "feminine", "f": "feminine", "fem": "feminine", "female": "feminine",
           "neuter": "neuter", "n": "neuter", "neut": "neuter", "other": "other", "common": "other"}
_NUMBER = {"singular": "singular", "sg": "singular", "sing": "singular", "s": "singular",
           "plural": "plural", "pl": "plural", "p": "plural", "uncountable": "uncountable",
           "mass": "uncountable", "mass noun": "uncountable", "non count": "uncountable",
           "other": "other"}


def _k(v: str) -> str:
    return re.sub(r"[\s_\-]+", " ", v.strip().lower())


_TAG = re.compile(r"</?(?:b|strong|i|em|u|span|font|sup|sub|p|div|a|mark|small|big)\b[^>]*>|<br\s*/?>", re.I)
_ENTITY = re.compile(r"&(?:#\d+|#x[0-9a-f]+|[a-z]+\d*);", re.I)


def clean_term(text: str) -> str:
    """Terms are matched against running text: HTML entities and markup a tool
    leaked into them would never match, so they are decoded and stripped."""
    out = text
    if _ENTITY.search(out):
        out = html.unescape(out)
    if _TAG.search(out):
        out = _TAG.sub(lambda m: " " if m.group(0).lower().startswith("<br") else "", out)
    out = strip_invalid_xml(out)
    return re.sub(r"[ \t]+", " ", out).strip()


# ------------------------------------------------------------------ preparation


def _parts(raw: str) -> list[str]:
    return [p.strip() for p in re.split(r"[|;,/]", raw or "") if p.strip()]


def _term_cells(t: Term, file: str, log: Log) -> dict[str, str]:
    """Vitra's term columns for a term. A value with no Vitra equivalent is kept,
    labelled, in the term's Note; every mapping is counted in the report."""
    f = t.fields
    notes: list[str] = []
    out: dict[str, str] = {}

    for part in _parts(f.get("status", "")):
        k = _k(part)
        if k in _FORBIDDEN:
            out["Forbidden"] = "yes"
            log.value(file, "Status", part, "Forbidden = yes")
        elif k in _PREFERRED:
            out["Preferred"] = "yes"
            out.setdefault("Status", "approved")
            log.value(file, "Status", part, "Preferred = yes")
        elif k in _STATUS:
            out.setdefault("Status", _STATUS[k])
            log.value(file, "Status", part, _STATUS[k])
        else:
            notes.append(f"Status: {part}")
            log.value(file, "Status", part, "(kept in Note)")
    for col, key in (("Forbidden", "forbidden"), ("Preferred", "preferred"),
                     ("Case sensitive", "case_sensitive"), ("Exact match", "exact_match")):
        if key in f:
            b = to_bool(f[key])
            kk = _k(f[key])
            if b is None and key == "forbidden" and kk in _FORBIDDEN:
                b = True
            elif b is None and key == "preferred" and kk in _PREFERRED:
                b = True
            if b is None:
                notes.append(f"{col}: {f[key]}")
                log.value(file, col, f[key], "(kept in Note)")
            elif b:
                out[col] = "yes"
    # Part of speech and term type share values in the wild ("Phrase", "Acronym" as a
    # part of speech; "Noun|Phrase"): each value goes where Vitra has it.
    for col, key in (("Part of speech", "part_of_speech"), ("Term type", "term_type")):
        for part in _parts(f.get(key, "")):
            k = _k(part)
            if k in _POS and "Part of speech" not in out:
                out["Part of speech"] = _POS[k]
                log.value(file, col, part, f"Part of speech = {_POS[k]}")
            elif k in _TERM_TYPE and "Term type" not in out:
                out["Term type"] = _TERM_TYPE[k]
                log.value(file, col, part, f"Term type = {_TERM_TYPE[k]}")
            elif k == "proper noun" and "Part of speech" not in out:
                out["Part of speech"] = "noun"
                notes.append(f"{col}: {part}")
                log.value(file, col, part, "Part of speech = noun (original kept in Note)")
            else:
                notes.append(f"{col}: {part}")
                log.value(file, col, part, "(kept in Note)")
    for col, key, table in (("Gender", "gender", _GENDER), ("Number", "number", _NUMBER)):
        if key in f:
            v = table.get(_k(f[key]))
            if v:
                out[col] = v
                log.value(file, col, f[key], v)
            else:
                notes.append(f"{col}: {f[key]}")
                log.value(file, col, f[key], "(kept in Note)")
    if f.get("usage"):
        out["Usage"] = f["usage"]
    if f.get("short_form"):
        out["Short form"] = f["short_form"]
    if f.get("note"):
        notes.insert(0, f["note"])
    notes += [f"{label}: {value}" for label, value in t.extra]
    if notes:
        out["Note"] = "\n".join(notes)
    return out


def prepare_concepts(concepts: list[Concept], file: str, log: Log, resolve: Resolver) -> list[Concept]:
    """Resolve languages, clean terms, drop empty concepts. Returns usable concepts."""
    ready = []
    for c in concepts:
        terms = []
        for t in c.terms:
            code = resolve(t.lang)
            if not code:
                log.exclude(file, t.where, "Term", t.lang, t.text, "",
                            f"Language '{t.lang}' is not in Vitra's language list" if t.lang else "No language")
                continue
            cleaned = clean_term(t.text)
            if not cleaned:
                log.exclude(file, t.where, "Term", code, t.text, "", "Empty term")
                continue
            if len(cleaned) > MAX_CELL_CHARS:
                log.exclude(file, t.where, "Term", code, t.text[:300], "", "Too long for a spreadsheet cell")
                continue
            if cleaned != t.text.strip():
                log.change(file, t.where, f"Term ({code})", t.text, cleaned,
                           "HTML codes or markup removed so the term matches real text")
                t.extra.append(("Original spelling", t.text))
            t.lang, t.text = code, cleaned
            terms.append(t)
        c.terms = terms
        if not terms:
            if c.fields or c.extra:
                log.exclude(file, c.where, "Concept", "", c.fields.get("definition", "")[:300], "",
                            "Concept has no usable terms")
            continue
        ready.append(c)
    return ready


def is_dnt(c: Concept, file_hint: bool) -> bool:
    if c.dnt is not None:
        return c.dnt
    flags = [t.dnt for t in c.terms if t.dnt is not None]
    if flags and all(flags):
        return True
    if flags and not any(flags):
        return False
    langs = {t.lang for t in c.terms}
    if len(langs) == 1:
        return file_hint
    texts = {norm_key(t.text) for t in c.terms}
    per_lang = Counter(t.lang for t in c.terms)
    return len(texts) == 1 and max(per_lang.values()) == 1


def source_language(concepts: list[Concept], given: str | None) -> str:
    if given:
        return given
    firsts = Counter(c.terms[0].lang for c in concepts if c.terms)
    return firsts.most_common(1)[0][0] if firsts else ""


# ------------------------------------------------------------------ term base


def _note_lines(c: Concept, dnt: bool) -> str:
    lines = []
    if c.fields.get("concept_note"):
        lines.append(c.fields["concept_note"])
    lines += [f"{label}: {value}" for label, value in c.extra]
    if dnt:
        lines.append("Do not translate.")
    return "\n".join(lines)


def tb_rows(concepts: list[Concept], dnt_flags: list[bool], file: str, log: Log) -> list[tuple[Concept, list[list[str]]]]:
    used: set[str] = set()
    out = []
    n = 0
    for c, dnt in zip(concepts, dnt_flags):
        n += 1
        cid = c.id.strip()
        if not cid or cid in used:
            cid = f"c{n}"
            while cid in used:
                n += 1
                cid = f"c{n}"
        used.add(cid)
        rows = []
        subs = c.fields.get("subdomains", "")
        concept_cells = [cid, c.fields.get("domain", ""), "; ".join(s.strip() for s in re.split(r"[;,]", subs) if s.strip()),
                         c.fields.get("url", ""), c.fields.get("definition", ""), _note_lines(c, dnt)]
        seen: dict[tuple[str, str], Term] = {}
        for i, t in enumerate(c.terms):
            # VitraTM keeps one term per (concept, language, text): case counts, spacing does not.
            key = (t.lang, norm_key(t.text))
            if key in seen:
                log.exclude(file, t.where, "Term", t.lang, t.text, "",
                            "Same term twice in one concept (the first one is kept)")
                continue
            seen[key] = t
            cells = _term_cells(t, file, log)
            row = (concept_cells if i == 0 else [cid, "", "", "", "", ""]) + [t.lang, t.text] + \
                [cells.get(h, "") for h in TB_HEADER[8:]]
            rows.append(row)
        out.append((c, rows))
    return out


def _groups(concepts_rows) -> list[list[int]]:
    """Concepts that share a term (language + text) go in the same file: VitraTM
    merges a concept into one from an EARLIER file that shares most of its terms,
    but never two concepts of the same file."""
    parent = list(range(len(concepts_rows)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    owner: dict[tuple[str, str], int] = {}
    for i, (c, _) in enumerate(concepts_rows):
        for t in c.terms:
            k = (t.lang, fold_key(t.text))
            if k in owner:
                parent[find(i)] = find(owner[k])
            else:
                owner[k] = i
    groups: dict[int, list[int]] = {}
    for i in range(len(concepts_rows)):
        groups.setdefault(find(i), []).append(i)
    return sorted(groups.values(), key=lambda g: g[0])


def write_term_base(concepts_rows, out_dir: str, base: str, log: Log, file: str,
                    max_concepts: int = LIMIT_TB_CONCEPTS, max_bytes: int = LIMIT_BYTES) -> list[dict]:
    groups = _groups(concepts_rows)
    chunks: list[list[int]] = [[]]
    for g in groups:
        if len(g) > max_concepts:
            log.note(f"{file}: {len(g)} concepts share terms with each other, more than one file holds; "
                     "they were split and may merge on import.")
        if chunks[-1] and len(chunks[-1]) + len(g) > max_concepts:
            chunks.append([])
        chunks[-1].extend(g)
    return _write_chunks(
        [[concepts_rows[i] for i in sorted(ch)] for ch in chunks if ch], out_dir, base, "Term base",
        lambda chunk: [("Terms", TB_HEADER, (r for _, rows in chunk for r in rows))],
        lambda chunk: {"concepts": len(chunk), "rows": sum(len(r) for _, r in chunk),
                       "languages": sorted({row[6] for _, rows in chunk for row in rows})},
        max_bytes)


# -------------------------------------------------------------------- glossary


def concepts_to_entries(concepts: list[Concept], dnt_flags: list[bool], src: str, file: str,
                        log: Log) -> list[GlossaryEntry]:
    entries = []
    for c, dnt in zip(concepts, dnt_flags):
        desc = [x for x in (c.fields.get("definition", ""), c.fields.get("concept_note", "")) if x]
        desc += [f"{label}: {value}" for label, value in c.extra]
        tags = [x for x in [c.fields.get("domain", "")] + re.split(r"[;,]", c.fields.get("subdomains", "")) if x.strip()]
        src_terms = [t for t in c.terms if t.lang == src] or [c.terms[0]]
        lang = src_terms[0].lang
        case_sensitive = next((to_bool(t.fields.get("case_sensitive")) for t in c.terms
                               if t.fields.get("case_sensitive")), None)
        if dnt:
            # Every spelling of a do-not-translate concept is its own entry: each must stay as is.
            seen: set[tuple[str, str]] = set()
            heads: list[GlossaryEntry] = []
            for t in c.terms:
                key = fold_key(t.text)
                if any(key == s for _, s in seen):
                    continue
                if t.lang != lang and any(fold_key(h.term) == key for h in heads):
                    continue
                if t.lang != lang:
                    # A different spelling in another language: kept as information.
                    if heads:
                        heads[0].description = "\n".join(filter(None, [heads[0].description,
                                                                        f"{t.lang} spelling in the source file: {t.text}"]))
                        log.change(file, t.where, f"Term ({t.lang})", t.text, "(in Description)",
                                   "Do-not-translate entry with a different spelling in this language")
                        continue
                seen.add((t.lang, key))
                e = GlossaryEntry(where=c.where, term=t.text, lang=t.lang, description="\n".join(desc),
                                  translatable=False, case_sensitive=case_sensitive, tags=list(tags))
                heads.append(e)
                entries.append(e)
            continue
        head = next((t for t in src_terms if _is_preferred(t)), src_terms[0])
        e = GlossaryEntry(where=c.where, term=head.text, lang=lang, description="\n".join(desc),
                          translatable=None, case_sensitive=case_sensitive, tags=list(tags))
        others = [t.text for t in src_terms if t is not head]
        if others:
            e.description = "\n".join(filter(None, [e.description, "Also: " + "; ".join(others)]))
        for code in dict.fromkeys(t.lang for t in c.terms if t.lang != lang):
            ts = [t for t in c.terms if t.lang == code]
            allowed = [t for t in ts if not _is_forbidden(t)]
            pick = next((t for t in allowed if _is_preferred(t)), allowed[0] if allowed else None)
            note = []
            if pick is not None:
                cells = _term_cells(pick, file, log)
                note += [f"{k}: {v}" for k, v in cells.items() if k not in ("Status", "Note") and v]
                if cells.get("Note"):
                    note.append(cells["Note"])
            also = [t.text for t in allowed if t is not pick]
            avoid = [t.text for t in ts if _is_forbidden(t)]
            if also:
                note.append("Also: " + "; ".join(also))
            if avoid:
                note.append("Do not use: " + "; ".join(avoid))
            if pick is None:
                e.description = "\n".join(filter(None, [e.description, f"{code}: do not use " + "; ".join(avoid)]))
                continue
            e.translations.append((code, pick.text, "\n".join(note)))
        entries.append(e)
    return entries


def _is_forbidden(t: Term) -> bool:
    s = _k(t.fields.get("status", ""))
    return to_bool(t.fields.get("forbidden")) is True or s in _FORBIDDEN


def _is_preferred(t: Term) -> bool:
    s = _k(t.fields.get("status", ""))
    return to_bool(t.fields.get("preferred")) is True or s in _PREFERRED


def prepare_entries(entries: list[GlossaryEntry], file: str, log: Log, resolve: Resolver) -> list[GlossaryEntry]:
    """Resolve languages, clean text, merge duplicates (VitraTM keys an entry by
    language + case-folded term, so two rows for one key would overwrite)."""
    merged: dict[tuple[str, str], GlossaryEntry] = {}
    for e in entries:
        code = resolve(e.lang)
        if not code:
            log.exclude(file, e.where, "Glossary entry", e.lang, e.term, "",
                        f"Language '{e.lang}' is not in Vitra's language list" if e.lang else "No language")
            continue
        term = clean_term(e.term)
        if not term:
            log.exclude(file, e.where, "Glossary entry", code, e.term, "", "Empty term")
            continue
        if term != e.term.strip():
            log.change(file, e.where, "Term", e.term, term, "HTML codes or markup removed")
        e.lang, e.term = code, term
        trs = []
        for lang, text, note in e.translations:
            t_code = resolve(lang)
            if not t_code:
                log.exclude(file, e.where, "Glossary translation", lang, e.term, text,
                            f"Language '{lang}' is not in Vitra's language list")
                continue
            if t_code == code:
                e.description = "\n".join(filter(None, [e.description, f"Also: {text}"]))
                log.change(file, e.where, f"Translation ({t_code})", text, "(in Description)",
                           "Same language as the entry itself")
                continue
            trs.append((t_code, clean_term(text), note))
        e.translations = trs
        key = (code, fold_key(term))
        first = merged.get(key)
        if first is None:
            merged[key] = e
            continue
        log.change(file, e.where, "Entry", e.term, f"merged into {first.where}",
                   "Same term and language as an earlier entry")
        have = {lang: i for i, (lang, _, _) in enumerate(first.translations)}
        for lang, text, note in e.translations:
            if lang not in have:
                first.translations.append((lang, text, note))
            elif fold_key(first.translations[have[lang]][1]) != fold_key(text):
                l0, t0, n0 = first.translations[have[lang]]
                first.translations[have[lang]] = (l0, t0, "\n".join(filter(None, [n0, f"Also: {text}"])))
        if e.description and e.description not in first.description:
            first.description = "\n".join(filter(None, [first.description, e.description]))
        first.tags = list(dict.fromkeys(first.tags + e.tags))
        if first.translatable is None:
            first.translatable = e.translatable
    return list(merged.values())


def write_glossary(entries: list[GlossaryEntry], out_dir: str, base: str,
                   max_entries: int = LIMIT_GLOSSARY_ENTRIES, max_bytes: int = LIMIT_BYTES) -> list[dict]:
    chunks = [entries[i:i + max_entries] for i in range(0, len(entries), max_entries)]

    def sheets(chunk):
        langs = sorted({lang for e in chunk for lang, _, _ in e.translations})
        has_note = {lang for e in chunk for lang, _, note in e.translations if note}
        header = GL_FIXED + [h for lang in langs for h in ([lang, f"{lang} note"] if lang in has_note else [lang])]

        def rows():
            for e in chunk:
                row = [e.term, e.lang, e.description,
                       "" if e.translatable is None else ("yes" if e.translatable else "no"),
                       "" if e.case_sensitive is None else ("yes" if e.case_sensitive else "no"),
                       "; ".join(e.tags)]
                tr = {lang: (text, note) for lang, text, note in e.translations}
                for lang in langs:
                    text, note = tr.get(lang, ("", ""))
                    row.append(text)
                    if lang in has_note:
                        row.append(note)
                yield row
        return [("Glossary", header, rows())]

    return _write_chunks(
        chunks, out_dir, base, "Glossary", sheets,
        lambda chunk: {"entries": len(chunk), "rows": len(chunk),
                       "do_not_translate": sum(1 for e in chunk if e.translatable is False),
                       "languages": sorted({e.lang for e in chunk} | {lang for e in chunk for lang, _, _ in e.translations})},
        max_bytes)


# ------------------------------------------------------------------- writing


def _write_chunks(chunks, out_dir, base, label, sheets_of, stats_of, max_bytes) -> list[dict]:
    written = []
    n = 0

    def emit(chunk):
        nonlocal n
        n += 1
        path = os.path.join(out_dir, f".{base}.{label}.{n}.tmp.xlsx")
        write_xlsx(path, sheets_of(chunk))
        if os.path.getsize(path) > max_bytes and len(chunk) > 1:
            os.remove(path)
            half = len(chunk) // 2
            emit(chunk[:half])
            emit(chunk[half:])
            return
        written.append((path, chunk))

    for ch in chunks:
        emit(ch)
    out = []
    for i, (tmp, chunk) in enumerate(written, 1):
        suffix = f" - part {i:02d} of {len(written):02d}" if len(written) > 1 else ""
        final = claim(os.path.join(out_dir, f"{base} - {label}{suffix}.xlsx"))
        os.replace(tmp, final)
        out.append({"file": final, "import_into": label, **stats_of(chunk), "bytes": os.path.getsize(final)})
    return out
