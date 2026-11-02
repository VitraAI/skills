"""Spreadsheets and delimited text (XLSX, CSV, TSV, TXT) from any tool.

Each sheet's header row is read into a column map: which column is source
text, target text, a language's term, a definition, and so on. The same map
can be written by hand and passed with --map when a layout is not recognized
(references/formats.md shows how). `inspect` prints the map it found.
"""

from __future__ import annotations

import csv
import io
import os
import re
import statistics
import sys

import _lang
from _fields import NOT_LANGUAGE_HEADERS, field_of, is_admin
from _model import Concept, GlossaryEntry, Log, Term, TmRow, clean_newlines, header_key, to_bool
from _readers import NeedsInput, Parsed, Unsupported
from _xlsx import XlsxReader

csv.field_size_limit(min(sys.maxsize, 2**31 - 1))

_TM_ALIASES = {
    "src_lang": {"source language", "source lang", "source locale", "srclang", "source language code",
                 "src lang", "source lang code", "from language", "from"},
    "tgt_lang": {"target language", "target lang", "target locale", "trglang", "tgtlang",
                 "target language code", "tgt lang", "to language", "to"},
    "src_text": {"source text", "source", "source segment", "original", "source string", "src",
                 "source content", "original text", "source term", "segment source", "key text"},
    "tgt_text": {"target text", "target", "translation", "target segment", "translated text",
                 "target string", "tgt", "target content", "translated", "target term",
                 "segment target"},
}
_TEXT_WORDS = {"", "term", "terms", "text", "translation", "target", "source", "segment", "string",
               "value", "content"}

_TERMS_HINT = re.compile(r"gloss|term|(^|[^a-z])tb([^a-z]|$)|dnt|do.?not.?translate|lexic|dictionar|"
                         r"brand|trademark|untranslat|vocab|nomenclat|wordlist|word.?list", re.I)
_DNT_HINT = re.compile(r"(^|[^a-z])dnt([^a-z]|$)|do.?not.?translate|untranslat|non.?translat|"
                       r"no.?translat|brand.?names?|trademarks?|keep.?(in.?english|as.?is)", re.I)


# ------------------------------------------------------------------------ loading


def _decode(raw: bytes, name: str, log: Log) -> str:
    if raw.startswith(b"\xef\xbb\xbf"):
        return raw[3:].decode("utf-8", errors="replace")
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        log.note(f"{name}: not UTF-8; read as Windows-1252. Check accented letters in the output.")
        return raw.decode("cp1252", errors="replace")


def load_sheets(path: str, fmt: str, name: str, log: Log) -> list[tuple[str, list[list[str]]]]:
    if fmt == "xlsx":
        rd = XlsxReader(path)
        try:
            return [(sn, [[clean_newlines(c) for c in r] for r in rd.rows(i)])
                    for i, sn in enumerate(rd.sheet_names)]
        finally:
            rd.close()
    with open(path, "rb") as fh:
        text = _decode(fh.read(), name, log)
    ext = os.path.splitext(path)[1].lower()
    if ext in (".tsv", ".tab"):
        delim = "\t"
    else:
        sample = "\n".join(text.splitlines()[:50])
        counts = {d: sample.count(d) for d in (",", ";", "\t", "|")}
        delim = max(counts, key=lambda d: counts[d]) if any(counts.values()) else ","
        try:
            delim = csv.Sniffer().sniff(sample, delimiters=",;\t|").delimiter
        except csv.Error:
            pass
    rows = [[clean_newlines(c) for c in r] for r in csv.reader(io.StringIO(text, newline=""), delimiter=delim)]
    return [("", [r for r in rows if any(c.strip() for c in r)])]


# ------------------------------------------------------------------- column roles


def _as_language(text: str, overrides: dict) -> str | None:
    t = text.strip()
    if not t.strip("()[]{} ") or t.strip("()[]{} ").lower() in NOT_LANGUAGE_HEADERS:
        return None
    return _lang.resolve(t, overrides) or _lang.resolve(t.strip("()[]{} "), overrides)


def _split_lang_field(header: str, overrides: dict) -> tuple[str, str] | None:
    """'de-DE note' -> ('de-DE', 'note'); 'Term (fr-FR)' -> ('fr-FR', 'term'); 'German' -> ('de', '')."""
    h = header.strip()
    code = _as_language(h, overrides)
    if code:
        return code, ""
    m = re.match(r"^(.*?)[\s_:\-]*[\(\[]\s*([^()\[\]]+?)\s*[\)\]]\s*(.*)$", h)
    if m:
        code = _as_language(m.group(2), overrides)
        rest = (m.group(1) + " " + m.group(3)).strip()
        if code and (header_key(rest) in _TEXT_WORDS or field_of(rest)):
            return code, rest
        code = _as_language(m.group(1), overrides)
        rest = m.group(2)
        if code and (header_key(rest) in _TEXT_WORDS or field_of(rest)):
            return code, rest
    cuts = [i for i, ch in enumerate(h) if ch in " _-:|/"]
    best = None
    for i in cuts:
        left, right = h[:i].strip(" _-:|/"), h[i + 1:].strip(" _-:|/")
        for lang_part, rest in ((left, right), (right, left)):
            code = _as_language(lang_part, overrides)
            if code and (header_key(rest) in _TEXT_WORDS or field_of(rest)):
                if best is None or len(lang_part) > best[2]:
                    best = (code, rest, len(lang_part))
    return (best[0], best[1]) if best else None


def column_roles(header: list[str], overrides: dict) -> list[dict]:
    roles = []
    for i, h in enumerate(header):
        k = header_key(h)
        spec: dict = {"col": i, "header": h}
        tm = next((r for r, names in _TM_ALIASES.items() if k in names), None)
        if not k:
            spec["role"] = "ignore"
        elif tm:
            spec["role"] = tm
        elif field_of(h) in ("language", "concept_id"):
            spec["role"] = field_of(h)
        elif " | " in h and _as_language(h.split(" | ", 1)[0], overrides):
            # A column under a language band (two header rows merged): "<language> | <field>".
            band, rest = h.split(" | ", 1)
            code = _as_language(band, overrides)
            if header_key(rest) in _TEXT_WORDS:
                spec.update(role="lang", lang=code, field="text")
            elif field_of(rest):
                spec.update(role="lang", lang=code, field=field_of(rest))
            elif is_admin(rest):
                spec["role"] = "admin"
            else:
                spec.update(role="lang", lang=code, field="extra", label=rest)
        else:
            lf = _split_lang_field(h, overrides)
            f = field_of(h)
            if lf and not f:
                code, rest = lf
                rf = "text" if header_key(rest) in _TEXT_WORDS else field_of(rest)
                if header_key(rest) == "source":
                    spec.update(role="src_text", lang=code)
                elif header_key(rest) in ("target", "translation"):
                    spec.update(role="tgt_text", lang=code)
                else:
                    spec.update(role="lang", lang=code, field=rf)
            elif f:
                spec.update(role="field", field=f)
            elif is_admin(h):
                spec["role"] = "admin"
            else:
                spec["role"] = "extra"
        roles.append(spec)
    return roles


def _score(row: list[str], overrides: dict) -> int:
    return sum(1 for s in column_roles(row, overrides) if s["role"] not in ("extra", "ignore", "admin"))


def _find_header(rows: list[list[str]], overrides: dict) -> int:
    best, best_i = 0, -1
    for i, r in enumerate(rows[:15]):
        s = _score(r, overrides)
        if s > best:
            best, best_i = s, i
    return best_i


def _is_language_band(rows: list[list[str]], hi: int, overrides: dict) -> bool:
    """A row naming languages over blocks of columns, field names in the row below
    (MultiTerm and many term-base Excel exports)."""
    if hi + 1 >= len(rows):
        return False
    band = rows[hi]
    filled = [c for c in band if c.strip()]
    langs = [c for c in filled if _as_language(c, overrides)]
    below = sum(1 for c in rows[hi + 1] if c.strip() and (field_of(c) or is_admin(c)))
    return len(langs) >= 1 and len(filled) * 2 <= len(rows[hi + 1]) and below >= 2


def _merge_band(band: list[str], fields: list[str], overrides: dict) -> list[str]:
    out, current = [], None
    for j, f in enumerate(fields):
        b = band[j].strip() if j < len(band) else ""
        if b:
            current = b if _as_language(b, overrides) else None
        out.append(f"{current} | {f}" if current and f.strip() else f)
    return out


# ------------------------------------------------------------------ map from --map


def roles_from_map(header: list[str], spec: dict, overrides: dict) -> list[dict]:
    """A hand-written column map: {"Header": "source text" | "text:de-DE" | "note:fr" | ...}."""
    given = {header_key(k): v for k, v in (spec.get("columns") or {}).items()}
    roles = []
    for i, h in enumerate(header):
        r = given.get(header_key(h))
        if r is None:
            roles.append({"col": i, "header": h, "role": "ignore"})
            continue
        s = {"col": i, "header": h}
        rk = header_key(r.split(":")[0]) if ":" in r else header_key(r)
        lang = r.split(":", 1)[1].strip() if ":" in r else ""
        code = _lang.resolve(lang, overrides) if lang else None
        if lang and not code:
            raise Unsupported(f"--map: '{lang}' in \"{r}\" is not a language code Vitra accepts")
        tm = next((k for k, names in _TM_ALIASES.items() if rk in names), None)
        if rk in ("ignore", "skip", ""):
            s["role"] = "ignore"
        elif rk in ("text", "term") and code:
            s.update(role="lang", lang=code, field="text")
        elif tm:
            s.update(role=tm, **({"lang": code} if code else {}))
        elif field_of(rk) in ("language", "concept_id"):
            s["role"] = field_of(rk)
        elif field_of(rk) and code:
            s.update(role="lang", lang=code, field=field_of(rk))
        elif field_of(rk):
            s.update(role="field", field=field_of(rk))
        elif rk in ("drop", "admin"):
            s["role"] = "admin"
        elif rk in ("extra", "keep"):
            s["role"] = "extra"
        else:
            raise Unsupported(f"--map: unknown role \"{r}\" for column \"{h}\"")
        roles.append(s)
    return roles


# -------------------------------------------------------------------- reading


def read_table(path: str, fmt: str, name: str, log: Log, opts) -> list[Parsed]:
    overrides = opts.lang_map
    mapping = opts.map_spec or {}
    results = []
    sheets = load_sheets(path, fmt, name, log)
    want = mapping.get("sheet")
    errors: list[tuple[str, Exception]] = []
    for idx, (sheet, rows) in enumerate(sheets):
        if want is not None and want not in (sheet, idx, str(idx + 1)):
            continue
        label = f"{name}" + (f" [{sheet}]" if sheet and len(sheets) > 1 else "")
        if not rows:
            continue
        try:
            p = _read_sheet(label, fmt, path, sheet, rows, sheets, mapping, overrides, log, opts)
        except (NeedsInput, Unsupported) as e:
            if len(sheets) == 1:
                raise
            errors.append((label, e))
            continue
        if p:
            results.append(p)
    if results:
        for label, e in errors:
            log.note(f"{label}: sheet skipped ({e}).")
    elif errors:
        raise errors[0][1]
    if not results:
        raise Unsupported("a spreadsheet with no data rows under a recognized header.")
    return results


def _read_sheet(label, fmt, path, sheet, rows, sheets, mapping, overrides, log, opts):
    if mapping.get("columns"):
        hi = int(mapping.get("header_row", 1)) - 1
        roles = roles_from_map(rows[hi], mapping, overrides)
    else:
        hi = _find_header(rows, overrides)
        if hi > 0 and _is_language_band(rows, hi - 1, overrides):
            hi -= 1
        if hi >= 0 and _is_language_band(rows, hi, overrides):
            rows[hi + 1] = _merge_band(rows[hi], rows[hi + 1], overrides)
            log.note(f"{label}: two header rows (languages over field names) read as one.")
            hi += 1
        if hi >= 0:
            roles = column_roles(rows[hi], overrides)
        else:
            width = max(len(r) for r in rows)
            if width > 2:
                raise Unsupported("a table whose columns were not recognized. Write a column map "
                                  "(references/formats.md) and pass it with --map.")
            # Headerless one- or two-column list.
            hi = -1
            roles = [{"col": 0, "header": "Column A", "role": "lang", "lang": None, "field": "text"}]
            if width == 2:
                roles.append({"col": 1, "header": "Column B", "role": "lang", "lang": None, "field": "text",
                              "target": True})
    header = rows[hi] if hi >= 0 else []
    body = rows[hi + 1:]
    start = hi + 2  # 1-based sheet row of the first data row
    return _build(label, fmt, roles, header, body, start, path, sheet, log, opts)


def _lang_from_filename(path: str, overrides: dict) -> tuple[str | None, str | None]:
    base = os.path.splitext(os.path.basename(path))[0]
    # Only full tags with a region or script (en-US, zh_Hant): a bare "de" or "it"
    # in a file name is far more often a word than a language.
    tokens = re.findall(r"(?<![A-Za-z])([A-Za-z]{2,3}[-_](?:[A-Za-z]{4}[-_])?(?:[A-Za-z]{2}|\d{3}|[A-Za-z]{4}))(?![A-Za-z])",
                        base)
    found = []
    for t in tokens:
        code = _lang.resolve(t, overrides)
        if code and code not in found:
            found.append(code)
    if len(found) == 2:
        return found[0], found[1]
    return None, None


def _looks_like_terms(values: list[str]) -> bool:
    words = [len(v.split()) for v in values if v.strip()][:500]
    if len(words) < 3:
        return True
    words.sort()
    p90 = words[int(len(words) * 0.9) - 1]
    return statistics.median(words) <= 3 and p90 <= 6


def _build(label, fmt, roles, header, body, start, path, sheet, log: Log, opts) -> Parsed | None:
    by = lambda role: [s for s in roles if s["role"] == role]  # noqa: E731
    fields = {s.get("field") for s in roles if s["role"] == "field"}
    lang_cols = [s for s in roles if s["role"] == "lang"]
    hint_text = f"{os.path.basename(path)} {sheet} {' '.join(header)}"
    terms_hint = bool(_TERMS_HINT.search(hint_text))
    dnt_hint = bool(_DNT_HINT.search(hint_text)) or "dnt" in fields
    # Columns only terminology has. Not "context", "domain" or "note": TM exports carry those too.
    term_fields = fields & {"definition", "part_of_speech", "gender", "forbidden", "preferred",
                            "term_type", "dnt", "translatable", "synonyms", "short_form", "term"}
    has_id = bool(by("concept_id"))
    mapping = {"header_row": start - 1, "columns": {s["header"]: _role_text(s) for s in roles}}
    if sheet:
        mapping["sheet"] = sheet
    forced = opts.as_kind
    if (opts.map_spec or {}).get("kind"):
        forced = {"tm": "tm", "terms": "terms", "termbase": "terms", "glossary": "glossary"}.get(
            opts.map_spec["kind"], forced)

    # Native glossary sheet (VitraTM / Phrase): Term + Language + a column per language.
    if by("language") and "term" in fields and (lang_cols or (fields & {"translatable", "tags"} and not has_id)):
        if forced in (None, "glossary"):
            p = Parsed(label, fmt, "glossary", kind_reason="Glossary layout: Term, Language and a column per language",
                       mapping={**mapping, "kind": "glossary"})
            _glossary_rows(p, roles, body, start, log, opts)
            return p
    if (by("src_text") and (by("tgt_text") or lang_cols) and forced != "terms"
            and not ((terms_hint or term_fields - {"term"}) and forced is None)):
        p = Parsed(label, fmt, "tm", kind_reason="Source and target text columns", mapping={**mapping, "kind": "tm"})
        _tm_pair_rows(p, roles, body, start, path, log, opts)
        return p
    if by("language") and (by("src_text") or "term" in fields or by("tgt_text")) and forced != "tm":
        p = Parsed(label, fmt, "terms", kind_reason="One term per row (Language + Term)",
                   mapping={**mapping, "kind": "terms"}, dnt_hint=dnt_hint)
        _long_term_rows(p, roles, body, start, log, opts)
        return p
    if by("src_text") and by("tgt_text"):
        p = Parsed(label, fmt, "terms", kind_reason="Source/target columns in a terminology file",
                   mapping={**mapping, "kind": "terms"}, dnt_hint=dnt_hint)
        _wide_term_rows(p, roles, body, start, path, log, opts)
        return p
    text_cols = [s for s in lang_cols if s.get("field") in ("text", None)]
    useful = [s for s in roles if s["role"] not in ("ignore", "admin")]
    if not text_cols and "term" not in fields and len(useful) == 1:
        # One column of terms under a header such as "Do not translate" or "Brand names".
        only = useful[0]
        only.update(role="lang", lang=None, field="text")
        text_cols = lang_cols = [only]
        mapping["columns"][only["header"]] = "text"
    if text_cols or "term" in fields:
        first = text_cols[0] if text_cols else next(s for s in roles if s.get("field") == "term")
        sample = [r[first["col"]] for r in body[:500] if first["col"] < len(r)]
        if forced:
            kind, reason, confident = forced, f"Chosen with --as {forced}", True
        elif term_fields - {"term"} or has_id:
            kind, reason, confident = "terms", "Terminology columns (" + ", ".join(sorted(term_fields - {'term'}) or ["concept id"]) + ")", True
        elif terms_hint:
            kind, reason, confident = "terms", "The file or sheet name says terminology", True
        elif len(text_cols) <= 1:
            kind, reason, confident = "terms", "A single list of terms", False
        elif _looks_like_terms(sample):
            kind, reason, confident = "terms", "Short entries (terms, not sentences)", False
        else:
            kind, reason, confident = "tm", "Sentence-length text in a column per language", False
        if kind == "tm":
            p = Parsed(label, fmt, "tm", kind_reason=reason, confident=confident, mapping={**mapping, "kind": "tm"})
            _tm_wide_rows(p, roles, body, start, log, opts)
        else:
            p = Parsed(label, fmt, "terms", kind_reason=reason, confident=confident,
                       mapping={**mapping, "kind": "terms"}, dnt_hint=dnt_hint)
            _wide_term_rows(p, roles, body, start, path, log, opts)
        return p
    raise Unsupported(f"{label}: no column holds text in a known language. Write a column map "
                      "(references/formats.md) and pass it with --map.")


def _role_text(s: dict) -> str:
    r = s["role"]
    if r == "lang":
        f = s.get("field") or "text"
        return f"{f}:{s['lang']}" if s.get("lang") else f
    if r in ("src_text", "tgt_text", "src_lang", "tgt_lang"):
        base = {"src_text": "source text", "tgt_text": "target text",
                "src_lang": "source language", "tgt_lang": "target language"}[r]
        return f"{base}:{s['lang']}" if s.get("lang") else base
    if r == "field":
        return s["field"]
    if r == "concept_id":
        return "concept id"
    return {"admin": "drop", "extra": "extra"}.get(r, r)


def _cell(row: list[str], col: int) -> str:
    return row[col] if col < len(row) else ""


# ----------------------------------------------------------------------- TM rows


def _need(code, option, what):
    if not code:
        raise NeedsInput(option, f"Which language is the {what} text in? Pass --{option} (for example en-US).")
    return code


def _tm_pair_rows(p: Parsed, roles, body, start, path, log, opts) -> None:
    src = next(s for s in roles if s["role"] == "src_text")
    tgts = [s for s in roles if s["role"] in ("tgt_text",) or (s["role"] == "lang" and s.get("field") == "text")]
    s_lang_col = next((s for s in roles if s["role"] == "src_lang"), None)
    t_lang_col = next((s for s in roles if s["role"] == "tgt_lang"), None)
    status_col = next((s for s in roles if s["role"] == "field" and s["field"] == "status"), None)
    fn_src, fn_tgt = _lang_from_filename(path, opts.lang_map)
    for s in roles:
        if s["role"] in ("extra", "admin") or (s["role"] == "field" and s["field"] != "status"):
            for r in body[:1]:
                log.drop_field(p.file, f"Column \"{s['header']}\"", _cell(r, s["col"]))
    for i, row in enumerate(body):
        where = f"row {start + i}"
        s_lang = _cell(row, s_lang_col["col"]) if s_lang_col else (src.get("lang") or opts.source_lang or fn_src)
        if not s_lang_col:
            _need(s_lang, "source-lang", "source")
        for t in tgts:
            if t["role"] == "lang":
                t_lang = t["lang"]
            elif t_lang_col:
                t_lang = _cell(row, t_lang_col["col"])
            else:
                t_lang = _need(t.get("lang") or opts.target_lang or fn_tgt, "target-lang", "target")
            status = _cell(row, status_col["col"]) if status_col else None
            p.tm_rows.append(TmRow(s_lang, _cell(row, src["col"]), t_lang, _cell(row, t["col"]), where,
                                   _tm_status(status)))


def _tm_wide_rows(p: Parsed, roles, body, start, log, opts) -> None:
    text_cols = [s for s in roles if s["role"] == "lang" and s.get("field") in ("text", None)]
    if not text_cols[0].get("lang"):
        text_cols[0]["lang"] = _need(opts.source_lang, "source-lang", "first column's")
        if len(text_cols) > 1 and not text_cols[1].get("lang"):
            text_cols[1]["lang"] = _need(opts.target_lang, "target-lang", "second column's")
    src_code = opts.source_lang and _lang.resolve(opts.source_lang, opts.lang_map)
    src = next((s for s in text_cols if s["lang"] == src_code), text_cols[0])
    status = {s["lang"]: s for s in roles if s["role"] == "lang" and s.get("field") == "status"}
    for s in roles:
        if s["role"] in ("extra", "admin", "field") or (s["role"] == "lang" and s.get("field") not in ("text", "status", None)):
            log.drop_field(p.file, f"Column \"{s['header']}\"", _cell(body[0], s["col"]) if body else "")
    for i, row in enumerate(body):
        for t in text_cols:
            if t is src:
                continue
            st = status.get(t["lang"])
            p.tm_rows.append(TmRow(src["lang"], _cell(row, src["col"]), t["lang"], _cell(row, t["col"]),
                                   f"row {start + i}", _tm_status(_cell(row, st["col"]) if st else None)))


def _tm_status(raw: str | None) -> str | None:
    s = (raw or "").strip().lower()
    if not s:
        return None
    if s in ("approved", "final", "signed off", "signed-off", "approvedsignoff", "confirmed", "locked",
             "proofread", "proofreaded", "reviewed 2"):
        return "approved"
    if s in ("verified", "reviewed", "approvedtranslation", "checked", "validated", "reviewed 1"):
        return "verified"
    if s in ("unverified", "translated", "draft", "new", "pending", "mt", "machine translation"):
        return "unverified"
    return "?" + s


# --------------------------------------------------------------------- term rows


def _apply_field(target, f: str, label: str, value: str, log: Log, file: str) -> None:
    """Put one value on a concept (Concept) or term (Term)."""
    if not value.strip():
        return
    value = value.strip()
    if isinstance(target, Concept):
        if f in ("dnt", "translatable"):
            b = to_bool(value)
            if b is not None:
                target.dnt = b if f == "dnt" else not b
                return
        if f in ("domain", "subdomains", "definition", "concept_note", "url"):
            if target.fields.get(f):
                target.extra.append((label, value))
            else:
                target.fields[f] = value
            return
        if f == "note":
            if target.fields.get("concept_note"):
                target.extra.append((label, value))
            else:
                target.fields["concept_note"] = value
            return
        target.extra.append((label, value))
        return
    if f in ("dnt", "translatable"):
        b = to_bool(value)
        if b is not None:
            target.dnt = b if f == "dnt" else not b
            return
    if f == "status" and target.fields.get("status"):
        # Several status columns (workflow + usage): all are read; forbidden wins.
        target.fields["status"] += f"; {value}"
        return
    if f in ("status", "forbidden", "preferred", "case_sensitive", "exact_match", "note", "usage",
             "short_form", "term_type", "part_of_speech", "gender", "number") and not target.fields.get(f):
        target.fields[f] = value
        return
    target.extra.append((label, value))


_CONCEPT_FIELDS = {"domain", "subdomains", "definition", "concept_note", "url", "tags"}


def _split_terms(cell: str) -> list[str]:
    """Several terms in one cell, one per line (how most tools export synonyms)."""
    return [t.strip() for t in cell.split("\n") if t.strip()]


def _wide_term_rows(p: Parsed, roles, body, start, path, log, opts) -> None:
    text_cols = [s for s in roles if (s["role"] == "lang" and s.get("field") in ("text", None))
                 or s["role"] in ("src_text", "tgt_text") or (s["role"] == "field" and s["field"] == "term")]
    fn_src, fn_tgt = _lang_from_filename(path, opts.lang_map)
    for s in text_cols:
        if s.get("lang"):
            continue
        if s["role"] in ("src_text",) or (s["role"] == "field") or (s["role"] == "lang" and not s.get("target")):
            s["lang"] = _need(_lang.resolve(opts.source_lang, opts.lang_map) if opts.source_lang else fn_src,
                              "source-lang", f"\"{s['header']}\"")
        else:
            s["lang"] = _need(_lang.resolve(opts.target_lang, opts.lang_map) if opts.target_lang else fn_tgt,
                              "target-lang", f"\"{s['header']}\"")
    lang_fields = [s for s in roles if s["role"] == "lang" and s.get("field") not in ("text", None)]
    # "English definition" next to an "English (United States)" column: same language.
    text_langs = {s["lang"] for s in text_cols}
    for s in lang_fields:
        if s.get("lang") and s["lang"] not in text_langs:
            same = [c for c in text_langs if c.split("-")[0] == s["lang"].split("-")[0]]
            if len(same) == 1:
                s["lang"] = same[0]
    concept_cols = [s for s in roles if s["role"] in ("field", "extra", "concept_id", "src_lang", "tgt_lang")
                    and not (s["role"] == "field" and s["field"] == "term")]
    admin = [s for s in roles if s["role"] == "admin"]
    id_col = next((s for s in concept_cols if s["role"] == "concept_id"), None)
    prev: Concept | None = None
    for i, row in enumerate(body):
        where = f"row {start + i}"
        c = Concept(where=where)
        continuation = bool(id_col and prev is not None and not _cell(row, id_col["col"]).strip())
        if continuation:
            # A row with no concept id under one that has one: more terms of that concept
            # (synonyms on their own rows, as MultiTerm and Excel term exports write them).
            c = prev
        added = len(c.terms)
        for s in text_cols:
            cell = _cell(row, s["col"])
            parts = _split_terms(cell)
            if len(parts) > 1:
                log.change(p.file, where, f"Term ({s['lang']})", cell, " / ".join(parts),
                           "One cell held several lines: each line became its own term")
            for txt in parts:
                c.terms.append(Term(lang=s["lang"], text=txt, where=where))
        row_terms = c.terms[added:]
        for s in lang_fields:
            v = _cell(row, s["col"]).strip()
            if not v:
                continue
            if s["field"] == "synonyms":
                for txt in _split_terms(v.replace(";", "\n")):
                    c.terms.append(Term(lang=s["lang"], text=txt, where=where))
                continue
            # This row's first term in that language; else (a field-only row) the latest one.
            first = (next((t for t in row_terms if t.lang == s["lang"]), None)
                     or next((t for t in reversed(c.terms) if t.lang == s["lang"]), None))
            label = s.get("label") or s["header"]
            if s["field"] in _CONCEPT_FIELDS or first is None:
                _apply_field(c, s["field"], f"{label} ({s['lang']})" if s["field"] == "extra" else label,
                             v, log, p.file)
            else:
                _apply_field(first, s["field"], label, v, log, p.file)
        for s in concept_cols:
            v = _cell(row, s["col"]).strip()
            if not v:
                continue
            if s["role"] == "concept_id":
                c.id = v
            elif s["role"] == "field" and s["field"] not in _CONCEPT_FIELDS | {"dnt", "translatable", "note"}:
                # A term field with no language: applies to every term of the row.
                for t in c.terms:
                    _apply_field(t, s["field"], s["header"], v, log, p.file)
            elif s["role"] == "field":
                _apply_field(c, s["field"], s["header"], v, log, p.file)
            else:
                c.extra.append((s["header"], v))
        for s in admin:
            v = _cell(row, s["col"]).strip()
            if v:
                log.drop_field(p.file, f"Column \"{s['header']}\"", v)
        if not continuation and (c.terms or c.fields or c.extra):
            p.concepts.append(c)
            prev = c


def _long_term_rows(p: Parsed, roles, body, start, log, opts) -> None:
    lang_col = next(s for s in roles if s["role"] == "language")
    term_col = next((s for s in roles if s["role"] == "src_text" or (s["role"] == "field" and s["field"] == "term")),
                    None) or next(s for s in roles if s["role"] == "tgt_text")
    id_col = next((s for s in roles if s["role"] == "concept_id"), None)
    others = [s for s in roles if s not in (lang_col, term_col, id_col) and s["role"] != "ignore"]
    by_id: dict[str, Concept] = {}
    current: Concept | None = None
    if not id_col:
        log.note(f"{p.file}: no concept id column, so a new concept starts each time the first "
                 "language comes round again.")
    for i, row in enumerate(body):
        where = f"row {start + i}"
        lang = _cell(row, lang_col["col"]).strip()
        text = _cell(row, term_col["col"]).strip()
        cid = _cell(row, id_col["col"]).strip() if id_col else ""
        if cid:
            c = by_id.get(cid)
            if c is None:
                c = Concept(where=where, id=cid)
                by_id[cid] = c
                p.concepts.append(c)
        elif current is not None and (id_col or not current.terms or current.terms[0].lang != lang):
            # A blank id continues the concept above (VitraTM's own rule); with no id
            # column at all, the first language coming round again starts a new one.
            c = current
        else:
            c = Concept(where=where)
            p.concepts.append(c)
        current = c
        t = Term(lang=lang, text=text, where=where) if text else None
        first_row = not c.terms
        for s in others:
            v = _cell(row, s["col"]).strip()
            if not v:
                continue
            f = s.get("field") if s["role"] in ("field", "lang") else None
            if s["role"] == "admin":
                log.drop_field(p.file, f"Column \"{s['header']}\"", v)
            elif f in _CONCEPT_FIELDS or f in ("dnt", "translatable") and t is None:
                if first_row or not c.fields.get(f):
                    _apply_field(c, f, s["header"], v, log, p.file)
            elif f and t is not None:
                _apply_field(t, f, s["header"], v, log, p.file)
            elif t is not None:
                t.extra.append((s["header"], v))
            else:
                c.extra.append((s["header"], v))
        if t:
            c.terms.append(t)


def _glossary_rows(p: Parsed, roles, body, start, log, opts) -> None:
    term_col = next(s for s in roles if s["role"] == "field" and s["field"] == "term")
    lang_col = next(s for s in roles if s["role"] == "language")
    notes = {s["lang"]: s for s in roles if s["role"] == "lang" and s.get("field") == "note"}
    for i, row in enumerate(body):
        where = f"row {start + i}"
        term = _cell(row, term_col["col"]).strip()
        if not term:
            continue
        e = GlossaryEntry(where=where, term=term, lang=_cell(row, lang_col["col"]).strip())
        extra = []
        for s in roles:
            v = _cell(row, s["col"]).strip()
            if not v or s in (term_col, lang_col):
                continue
            f = s.get("field")
            if s["role"] == "field" and f in ("definition", "concept_note", "note"):
                e.description = (e.description + "\n" + v).strip() if e.description else v
            elif s["role"] == "field" and f in ("translatable", "dnt"):
                b = to_bool(v)
                e.translatable = None if b is None else (b if f == "translatable" else not b)
            elif s["role"] == "field" and f == "case_sensitive":
                e.case_sensitive = to_bool(v)
            elif s["role"] == "field" and f in ("tags", "domain", "subdomains"):
                e.tags += [t.strip() for t in re.split(r"[;,]", v) if t.strip()]
            elif s["role"] == "lang" and f in ("text", None):
                note = _cell(row, notes[s["lang"]]["col"]).strip() if s["lang"] in notes else ""
                e.translations.append((s["lang"], v, note))
            elif s["role"] == "lang" and f == "note":
                continue
            elif s["role"] == "admin":
                log.drop_field(p.file, f"Column \"{s['header']}\"", v)
            else:
                extra.append(f"{s['header']}: {v}")
        if extra:
            e.description = "\n".join(([e.description] if e.description else []) + extra)
        p.entries.append(e)
