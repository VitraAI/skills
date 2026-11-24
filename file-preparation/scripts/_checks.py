"""Data checks: problems in the client's own data that a person should see.

Nothing here changes or drops anything. Each finding is one line in the report's
"Issues" sheet: what was found, where, and what Vitra will hold after the
import. `inspect` counts them per check, so the user hears about them before
anything is converted.

Level "check": worth a person's look (a broken bracket, a placeholder, a
conflict). Level "info": how the data is, for the record (a term that exists in
only some languages, a translation identical to its source).
"""

from __future__ import annotations

import re
from collections import defaultdict

from _model import Concept, GlossaryEntry, Log, fold_key, norm_key

_TAG = re.compile(r"</?(\d+)/?>")
_ENTITY_TEXT = re.compile(r"&(?:amp|lt|gt|quot|apos|nbsp|#\d+|#x[0-9a-f]+);", re.I)
SPECIAL_SPACES = re.compile(r"[    　​\t]")
# Several alternatives in one cell: "a/b", "a；b", "a; b", "a | b".
_ALTERNATIVES = re.compile(r"\s*(?:；|;|\||/)\s*")
_PAIRS = (("(", ")"), ("[", "]"), ("{", "}"), ("（", "）"), ("【", "】"), ("«", "»"), ("“", "”"))
_ELLIPSIS = re.compile(r"…|\.\.\.")


def _short(text: str, n: int = 200) -> str:
    text = text.replace("\n", " ⏎ ")
    return text if len(text) <= n else text[: n - 1] + "…"


def _spaces(text: str) -> list[str]:
    names = {" ": "no-break space", " ": "narrow no-break space", " ": "figure space",
             " ": "thin space", "　": "ideographic space", "​": "zero-width space", "\t": "tab"}
    return sorted({names[c] for c in SPECIAL_SPACES.findall(text)})


def unbalanced(text: str) -> str | None:
    for o, c in _PAIRS:
        if text.count(o) != text.count(c):
            return f"{text.count(o)} × \"{o}\" but {text.count(c)} × \"{c}\""
    return None


def alternatives(term: str, source: str) -> list[str] | None:
    """The parts of a target term that holds several alternatives the source does not."""
    if _ALTERNATIVES.search(source or "") or "://" in term:
        return None
    parts = [p for p in _ALTERNATIVES.split(term) if p.strip()]
    if len(parts) < 2 or any(len(p) > 60 for p in parts):
        return None
    if all(len(p.strip()) <= 2 for p in parts):
        return None  # "m/s", "I/O": units and short codes, not alternatives
    if inflection(term):
        return None
    return parts


_INFLECTION = re.compile(r"\w/(?:[a-zäöüßàèéìòù]{1,3})(?:/[a-zäöüßàèéìòù]{1,3})*(?=$|[\s,.;:!?)])")


def inflection(term: str) -> bool:
    """Ending shorthand such as "Welche/s/r" or "il/la": one word, several endings."""
    return bool(_INFLECTION.search(term))


# ------------------------------------------------------------------------- TM


def check_units(units, file: str, log: Log) -> None:
    for s_code, src, translations in units:
        src_tags = sorted(_TAG.findall(src))
        if src_tags and not _TAG.sub("", src).strip(" \t\n.,;:!?-–—"):
            log.issue(file, "", "TM", "Only tags, no text", _short(src), "The source is nothing but tags",
                      "Imported as written", "info")
        for t_code, tgt, _ in translations:
            item = f"{_short(src, 120)} → {_short(tgt, 120)}"
            if sorted(_TAG.findall(tgt)) != src_tags:
                log.issue(file, t_code, "TM", "Tags differ", item,
                          f"Source tags {_tag_list(src)}; translation tags {_tag_list(tgt)}",
                          "Imported as written; check the tags in the translation", "check")
            if src.count("\n") != tgt.count("\n"):
                log.issue(file, t_code, "TM", "Line breaks differ", item,
                          f"{src.count(chr(10))} line break(s) in the source, {tgt.count(chr(10))} in the translation",
                          "Imported as written", "check")
            if norm_key(src) == norm_key(tgt) and re.search(r"[^\W\d_]", src):
                log.issue(file, t_code, "TM", "Translation same as source", _short(src),
                          "Often a name, a URL or code; sometimes an untranslated segment",
                          "Imported as written", "info")
            ent = _ENTITY_TEXT.findall(src + " " + tgt)
            if ent:
                log.issue(file, t_code, "TM", "HTML code written as text", item,
                          "Contains " + ", ".join(sorted(set(ent))) + " as literal text",
                          "Kept exactly as written (not decoded)", "info")


def _tag_list(text: str) -> str:
    found = _TAG.findall(text)
    return ", ".join(f"<{n}>" for n in sorted(set(found), key=int)) if found else "none"


# ------------------------------------------------------------------ terminology


def check_terms(concepts: list[Concept], src: str, file: str, log: Log, asset: str,
                split_alternatives: bool, fix_spaces: bool) -> None:
    """Term-level and concept-level findings for one term base or glossary output."""
    all_langs = sorted({t.lang for c in concepts for t in c.terms})
    by_source: dict[str, list[Concept]] = defaultdict(list)
    for c in concepts:
        s_terms = [t for t in c.terms if t.lang == src]
        s_text = s_terms[0].text if s_terms else ""
        if s_text:
            by_source[fold_key(s_text)].append(c)
        for t in c.terms:
            where = t.where or c.where
            item = f"{s_text} → {t.text}" if t.lang != src and s_text else t.text
            bad = unbalanced(t.text)
            if bad:
                log.issue(file, where, asset, "Unbalanced brackets", f"{t.lang}: {item}", bad,
                          "Imported as written; the term only matches text written the same way", "check")
            if t.lang != src and s_text:
                parts = alternatives(t.text, s_text)
                if parts:
                    log.issue(file, where, asset, "Several alternatives in one term", f"{t.lang}: {item}",
                              f"{len(parts)} alternatives: " + " | ".join(parts),
                              "Split into separate terms" if split_alternatives else
                              "Imported as ONE term, exactly as written", "check")
                if inflection(t.text):
                    log.issue(file, where, asset, "Ending shorthand in a term", f"{t.lang}: {item}",
                              "Several word endings written with slashes (e.g. Welche/s/r)",
                              "Imported as written; it matches only text written the same way", "info")
                if ("(" in t.text or "（" in t.text) and "(" not in s_text and "（" not in s_text:
                    log.issue(file, where, asset, "Translation adds a bracketed explanation", f"{t.lang}: {item}",
                              "The translation carries text in brackets the source does not have",
                              "Imported as written", "info")
            sp = _spaces(t.text)
            if sp:
                log.issue(file, where, asset, "Special spaces in a term", f"{t.lang}: {item}",
                          "Contains " + ", ".join(sp),
                          "Replaced with normal spaces" if fix_spaces else "Imported as written", "check")
            if t.lang == src and _ELLIPSIS.search(t.text):
                log.issue(file, where, asset, "Template term with …", f"{t.lang}: {t.text}",
                          "An unfinished phrase; it matches only text that contains it as written",
                          "Imported as written", "info")
        langs = {t.lang for t in c.terms}
        if len(all_langs) > 2 and langs != set(all_langs):
            missing = [x for x in all_langs if x not in langs]
            log.issue(file, c.where, asset, "Not in every language", s_text or c.terms[0].text,
                      "No term in " + ", ".join(missing), "Imported with the languages it has", "info")
    for key, group in by_source.items():
        if len(group) < 2:
            continue
        defs = {fold_key(c.fields.get("definition", "")) for c in group}
        name = next(t.text for t in group[0].terms if t.lang == src)
        wheres = ", ".join(c.where for c in group[:6])
        if len(defs) == len(group) and "" not in defs:
            log.issue(file, wheres, asset, "Same term, different meanings", name,
                      f"{len(group)} concepts with different definitions",
                      "Kept as separate concepts (one per meaning)", "info")
        else:
            log.issue(file, wheres, asset, "Same term in several concepts", name,
                      f"{len(group)} concepts share this {src} term (and their definition, if any)",
                      "Kept separate unless you choose to merge them", "check")


def check_glossary_routing(c: Concept, src: str, file: str, log: Log) -> None:
    s = next((t.text for t in c.terms if t.lang == src), c.terms[0].text)
    other = sorted({f"{t.lang}: {t.text}" for t in c.terms if t.lang != src and fold_key(t.text) != fold_key(s)})
    if not other:
        return  # kept as is where listed; reported as "Do-not-translate in some languages only"
    log.issue(file, c.where, "Glossary", "Translated entry on a do-not-translate list", s,
              "Translated as " + "; ".join(other), "Imported as a translatable entry with these translations",
              "check")


def check_tb_vs_glossary(tb: list[tuple[str, Concept]], gl: list[tuple[str, GlossaryEntry]], log: Log) -> None:
    """Where a glossary and a term base of the same run disagree on a term's translation
    (a do-not-translate entry the term base translates, or two different translations)."""
    by_term: dict[tuple[str, str], list[tuple[str, GlossaryEntry]]] = defaultdict(list)
    for file, e in gl:
        by_term[(e.lang, fold_key(e.term))].append((file, e))
    for file, c in tb:
        for s in c.terms:
            for g_file, e in by_term.get((s.lang, fold_key(s.text)), []):
                wanted = {lang: text for lang, text, _ in e.translations}
                clashes = []
                for lang in sorted({t.lang for t in c.terms if t.lang != s.lang}):
                    want = e.term if e.translatable is False else wanted.get(lang)
                    have = [t.text for t in c.terms if t.lang == lang]
                    if want is not None and fold_key(want) not in {fold_key(h) for h in have}:
                        clashes.append(f"{lang}: glossary \"{want}\", term base \"{' / '.join(have)}\"")
                if clashes:
                    log.issue(f"{file} + {g_file}", c.where, "Term base vs glossary",
                              "Glossary and term base disagree", s.text,
                              ("Do-not-translate in the glossary. " if e.translatable is False else "") +
                              "; ".join(clashes),
                              "Both imported as they are. Decide which one is right and fix the other", "check")
