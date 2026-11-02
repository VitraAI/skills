"""Detect what a client file is and read the structured formats.

TMX, XLIFF (1.2 and 2.x, with the Trados, memoQ and Phrase dialects), SDLTM
(Trados Studio memories), gettext PO, TBX (v2 and v3) and MultiTerm XML.
Spreadsheets and delimited text are read in _tables.py.

Client files are data. Nothing here executes or fetches anything a file names:
ElementTree never resolves external entities, and SQLite files are opened
read-only.
"""

from __future__ import annotations

import os
import re
import sqlite3
import zipfile
from dataclasses import dataclass, field
from xml.etree import ElementTree as ET

from _fields import field_of, is_admin
from _model import Concept, GlossaryEntry, Log, Term, TmRow, clean_newlines, to_bool

XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"


@dataclass
class Parsed:
    file: str
    format: str
    kind: str  # tm | terms | glossary
    tool: str = ""
    kind_reason: str = ""
    confident: bool = True
    tm_rows: list[TmRow] = field(default_factory=list)
    concepts: list[Concept] = field(default_factory=list)
    entries: list[GlossaryEntry] = field(default_factory=list)
    # What a spreadsheet's columns were read as, for `inspect` and --map.
    mapping: dict | None = None
    dnt_hint: bool = False


class Unsupported(Exception):
    """A file this skill cannot read, with what the user can do instead."""


# ---------------------------------------------------------------------- detection

_UNSUPPORTED_EXT = {
    ".sdltb": "a MultiTerm term base (.sdltb). In MultiTerm, export it as MultiTerm XML or TBX.",
    ".mdb": "an Access database. Export the term base as MultiTerm XML, TBX or a spreadsheet.",
    ".tmq": "a memoQ memory package. In memoQ, export the memory as TMX.",
    ".mtm": "a memoQ memory. In memoQ, export it as TMX.",
    ".mqtb": "a memoQ term base. In memoQ, export it as TBX, MultiTerm XML or CSV.",
    ".tm": "a native memory file. Export it from its tool as TMX.",
    ".ods": "an OpenDocument spreadsheet. Save it as .xlsx or .csv.",
    ".numbers": "a Numbers spreadsheet. Export it as .xlsx or .csv.",
    ".docx": "a Word document. Terminology or translations in a Word table: save the table as .xlsx.",
    ".pdf": "a PDF. Ask the client for the source spreadsheet, TMX or TBX instead.",
}


def _xml_root(head: bytes) -> str:
    if head.startswith(b"\xff\xfe") or head.startswith(b"\xfe\xff"):
        text = head.decode("utf-16", errors="ignore")
    else:
        text = head.decode("utf-8", errors="ignore")
    text = re.sub(r"<\?.*?\?>|<!--.*?-->|<!DOCTYPE[^>]*>", "", text, flags=re.S)
    m = re.search(r"<\s*([A-Za-z_][\w.\-]*:)?([A-Za-z_][\w.\-]*)", text)
    return m.group(2).lower() if m else ""


def detect(path: str) -> str:
    """The real format, from the content: tmx, xliff, tbx, multiterm, sdltm, po,
    xlsx, csv, zip. Raises Unsupported with advice for anything else."""
    ext = os.path.splitext(path)[1].lower()
    with open(path, "rb") as fh:
        head = fh.read(8192)
    if not head:
        raise Unsupported("The file is empty.")
    if head.startswith(b"PK\x03\x04"):
        with zipfile.ZipFile(path) as z:
            names = z.namelist()
        if "xl/workbook.xml" in names:
            return "xlsx"
        if any(n.startswith("word/") for n in names):
            raise Unsupported(_UNSUPPORTED_EXT[".docx"])
        if "content.xml" in names:
            raise Unsupported(_UNSUPPORTED_EXT[".ods"])
        return "zip"
    if head.startswith(b"SQLite format 3\x00"):
        return "sdltm"
    if head.startswith(b"\xd0\xcf\x11\xe0"):
        raise Unsupported("an old binary Excel file (.xls). Open it in Excel and save it as .xlsx.")
    if b"Standard Jet DB" in head[:64] or b"Standard ACE DB" in head[:64]:
        raise Unsupported(_UNSUPPORTED_EXT.get(ext, _UNSUPPORTED_EXT[".mdb"]))
    if head.startswith(b"%PDF"):
        raise Unsupported(_UNSUPPORTED_EXT[".pdf"])
    stripped = head.lstrip(b"\xef\xbb\xbf\xff\xfe \t\r\n").replace(b"\x00", b"")
    if stripped.startswith(b"<"):
        root = _xml_root(head)
        if root == "tmx":
            return "tmx"
        if root == "xliff":
            return "xliff"
        if root in ("martif", "tbx"):
            return "tbx"
        if root == "mtf":
            return "multiterm"
        raise Unsupported(f"an XML file whose root is <{root}>, not TMX, XLIFF, TBX or MultiTerm XML.")
    if ext in _UNSUPPORTED_EXT:
        raise Unsupported(_UNSUPPORTED_EXT[ext])
    sample = head.replace(b"\x00", b"").decode("utf-8", errors="ignore")
    if ext in (".po", ".pot") or re.search(r'^msgid\s+"', sample, re.M):
        return "po"
    return "csv"


# ---------------------------------------------------------------------- XML text


def _local(tag) -> str:
    return tag.rsplit("}", 1)[-1] if isinstance(tag, str) else ""


def _text(el: ET.Element | None, drop: frozenset = frozenset()) -> str:
    """Text of an element; the CONTENT of `drop` elements is skipped, their tail kept."""
    if el is None:
        return ""
    parts = [el.text or ""]
    for ch in el:
        if _local(ch.tag) not in drop:
            parts.append(_text(ch, drop))
        parts.append(ch.tail or "")
    return "".join(parts)


def _plain(el: ET.Element | None) -> str:
    return clean_newlines("".join(el.itertext())).strip() if el is not None else ""


# TMX / XLIFF 1.2 inline elements that hold the native code of a tag, not text.
# The same set VitraTM drops (vitra-tm segment/io/tmx.ts, xliff.ts), so a file
# converted here reads exactly as the same file uploaded directly.
_CODE_TMX = frozenset({"bpt", "ept", "ph", "it", "ut"})
_CODE_XLIFF1 = frozenset({"bpt", "ept", "ph", "it"})
_CODE_XLIFF2 = frozenset({"ph", "sc", "ec", "cp", "sm", "em"})


# --------------------------------------------------------------------------- TMX


def read_tmx(path: str, name: str, log: Log) -> Parsed:
    out = Parsed(name, "tmx", "tm", kind_reason="TMX is a translation memory format")
    header_src = ""
    n = 0
    for _, el in ET.iterparse(path, events=("end",)):
        tag = _local(el.tag)
        if tag == "header":
            header_src = el.get("srclang", "")
            out.tool = " ".join(x for x in (el.get("creationtool", ""), el.get("creationtoolversion", "")) if x)
            continue
        if tag != "tu":
            continue
        n += 1
        where = f"TU {n}" + (f" (tuid {el.get('tuid')})" if el.get("tuid") else "")
        tuvs = []
        for tuv in el:
            if _local(tuv.tag) != "tuv":
                continue
            lang = tuv.get(XML_LANG) or tuv.get("lang") or ""
            seg = next((c for c in tuv if _local(c.tag) == "seg"), None)
            status = None
            for p in tuv:
                if _local(p.tag) == "prop" and p.get("type") == "x-vitra-review-status":
                    status = (p.text or "").strip().lower() or None
            date = tuv.get("changedate") or tuv.get("creationdate") or ""
            tuvs.append((lang, clean_newlines(_text(seg, _CODE_TMX)), status, date))
        for c in el:
            t = _local(c.tag)
            if t == "prop":
                key = f"TMX <prop type=\"{c.get('type', '')}\">"
                log.drop_field(name, key, (c.text or "").strip())
            elif t == "note":
                log.drop_field(name, "TMX <note>", (c.text or "").strip())
        tu_date = el.get("changedate") or el.get("creationdate") or ""
        src_lang = el.get("srclang") or header_src
        if not src_lang or src_lang == "*all*":
            src_lang = tuvs[0][0] if tuvs else ""
        src = next((t for t in tuvs if t[0].lower() == src_lang.lower()), None)
        el.clear()
        if src is None:
            log.exclude(name, where, "TM", src_lang, "", "", "No text in the source language")
            continue
        for lang, text, status, date in tuvs:
            if lang.lower() == src_lang.lower():
                continue
            out.tm_rows.append(TmRow(src[0], src[1], lang, text, where, status, date or tu_date))
    return out


# ------------------------------------------------------------------------- XLIFF

def _v1_status(state: str, approved: str) -> str | None:
    if state == "final":
        return "approved"
    if state == "signed-off" or approved == "yes":
        return "verified"
    return "unverified" if state else None


def _sdl_status(conf: str | None) -> str | None:
    if not conf:
        return None
    if conf == "ApprovedSignOff":
        return "approved"
    if conf == "ApprovedTranslation":
        return "verified"
    return "unverified"


def read_xliff(path: str, name: str, log: Log) -> Parsed:
    out = Parsed(name, "xliff", "tm", kind_reason="XLIFF is a bilingual translation file")
    root = ET.parse(path).getroot()
    version = root.get("version", "")
    if version.startswith("2") or root.get("srcLang"):
        _xliff2(root, name, out, log)
    else:
        _xliff1(root, name, out, log)
    return out


def _segments(el: ET.Element | None) -> dict[str, str]:
    """Trados-style <mrk mtype="seg" mid> segments of a <seg-source>/<target>."""
    found: dict[str, str] = {}
    if el is None:
        return found
    for m in el.iter():
        if _local(m.tag) == "mrk" and m.get("mtype") == "seg":
            found[m.get("mid", "")] = clean_newlines(_text(m, _CODE_XLIFF1))
    return found


def _xliff1(root: ET.Element, name: str, out: Parsed, log: Log) -> None:
    for f in root.iter():
        if _local(f.tag) != "file":
            continue
        out.tool = out.tool or f.get("tool-id", "") or f.get("tool", "")
        src_lang = f.get("source-language", "")
        tgt_lang = f.get("target-language", "")
        for tu in f.iter():
            if _local(tu.tag) != "trans-unit":
                continue
            where = f"trans-unit {tu.get('id', '?')}"
            if tu.get("translate") == "no":
                log.exclude(name, where, "TM", src_lang, "", "", "Marked translate=\"no\"")
                continue
            kids = {_local(c.tag): c for c in tu}
            source, target = kids.get("source"), kids.get("target")
            s_lang = (source.get(XML_LANG) if source is not None else None) or src_lang
            t_lang = (target.get(XML_LANG) if target is not None else None) or tgt_lang
            seg_src = _segments(kids.get("seg-source"))
            if seg_src:
                seg_tgt = _segments(target)
                confs = {}
                for d in tu.iter():
                    if _local(d.tag) == "seg" and d.get("id") is not None:
                        confs[d.get("id")] = d.get("conf")
                for mid, s_text in seg_src.items():
                    t_text = seg_tgt.get(mid, "")
                    w = f"{where}, segment {mid}"
                    if not t_text.strip():
                        log.exclude(name, w, "TM", t_lang, s_text, "", "Not translated (empty target)")
                        continue
                    out.tm_rows.append(TmRow(s_lang, s_text, t_lang, t_text, w, _sdl_status(confs.get(mid))))
                continue
            s_text = clean_newlines(_text(source, _CODE_XLIFF1))
            t_text = clean_newlines(_text(target, _CODE_XLIFF1)) if target is not None else ""
            if not t_text.strip():
                log.exclude(name, where, "TM", t_lang, s_text, "", "Not translated (no target)")
                continue
            status = _v1_status(target.get("state", ""), tu.get("approved", ""))
            out.tm_rows.append(TmRow(s_lang, s_text, t_lang, t_text, where, status))
            if tu.get("resname"):
                log.drop_field(name, "XLIFF resname (string key)", tu.get("resname"))
            for c in tu:
                if _local(c.tag) == "note":
                    log.drop_field(name, "XLIFF <note>", _plain(c))


def _xliff2(root: ET.Element, name: str, out: Parsed, log: Log) -> None:
    src_lang, tgt_lang = root.get("srcLang", ""), root.get("trgLang", "")
    for unit in root.iter():
        if _local(unit.tag) != "unit":
            continue
        uid = unit.get("id", "?")
        if unit.get("translate") == "no":
            log.exclude(name, f"unit {uid}", "TM", src_lang, "", "", "Marked translate=\"no\"")
            continue
        n = 0
        for seg in unit:
            if _local(seg.tag) != "segment":
                continue
            n += 1
            where = f"unit {uid}, segment {seg.get('id') or n}"
            kids = {_local(c.tag): c for c in seg}
            s_text = clean_newlines(_text(kids.get("source"), _CODE_XLIFF2))
            target = kids.get("target")
            t_text = clean_newlines(_text(target, _CODE_XLIFF2)) if target is not None else ""
            if not t_text.strip():
                log.exclude(name, where, "TM", tgt_lang, s_text, "", "Not translated (no target)")
                continue
            state = seg.get("state", "")
            status = {"final": "approved", "reviewed": "verified"}.get(state, "unverified" if state else None)
            out.tm_rows.append(TmRow(src_lang, s_text, tgt_lang, t_text, where, status))


# ------------------------------------------------------------------------- SDLTM


def _sdl_segment(xml: str | None) -> tuple[str, str]:
    """(culture, text) of a Trados Studio segment; tags dropped, text kept."""
    if not xml:
        return "", ""
    root = ET.fromstring(xml)
    culture, parts = "", []
    for el in root:
        tag = _local(el.tag)
        if tag == "CultureName":
            culture = (el.text or "").strip()
        elif tag == "Elements":
            for item in el:
                if _local(item.tag) == "Text":
                    v = next((c for c in item if _local(c.tag) == "Value"), None)
                    parts.append(v.text or "" if v is not None else "")
    return culture, clean_newlines("".join(parts))


def read_sdltm(path: str, name: str, log: Log) -> Parsed:
    out = Parsed(name, "sdltm", "tm", tool="Trados Studio", kind_reason="SDLTM is a Trados Studio memory")
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "translation_units" not in tables:
            raise Unsupported("a SQLite database that is not a Trados Studio memory (no translation_units table).")
        cols = {r[1] for r in con.execute("PRAGMA table_info(translation_units)")}
        date_col = "change_date" if "change_date" in cols else ("creation_date" if "creation_date" in cols else "NULL")
        tm_langs = ("", "")
        if "translation_memories" in tables:
            r = con.execute("SELECT source_language, target_language FROM translation_memories LIMIT 1").fetchone()
            if r:
                tm_langs = (r[0] or "", r[1] or "")
        q = f"SELECT id, source_segment, target_segment, {date_col} FROM translation_units ORDER BY id"
        for tu_id, s_xml, t_xml, date in con.execute(q):
            where = f"TU id {tu_id}"
            try:
                s_lang, s_text = _sdl_segment(s_xml)
                t_lang, t_text = _sdl_segment(t_xml)
            except ET.ParseError as e:
                log.exclude(name, where, "TM", "", "", "", f"Unreadable segment XML: {e}")
                continue
            out.tm_rows.append(TmRow(s_lang or tm_langs[0], s_text, t_lang or tm_langs[1], t_text,
                                     where, None, str(date or "")))
        for table in ("string_attributes", "numeric_attributes", "date_attributes",
                      "picklist_attributes", "multiple_string_attributes", "multiple_picklist_attributes"):
            if table in tables:
                count = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
                for _ in range(min(count, 1)):
                    log.drop_field(name, f"Trados field values ({table})", f"{count} values")
    finally:
        con.close()
    return out


# ---------------------------------------------------------------------------- PO

_PO_ESC = {"n": "\n", "t": "\t", '"': '"', "\\": "\\", "r": "\r"}


def _po_unquote(s: str) -> str:
    s = s.strip()
    if s.startswith('"') and s.endswith('"'):
        s = s[1:-1]
    return re.sub(r'\\(.)', lambda m: _PO_ESC.get(m.group(1), m.group(1)), s)


def read_po(path: str, name: str, log: Log, source_lang: str) -> Parsed:
    out = Parsed(name, "po", "tm", tool="gettext", kind_reason="PO is a gettext translation file")
    with open(path, "rb") as fh:
        raw = fh.read()
    text = raw.decode("utf-8-sig", errors="replace")
    entries: list[dict] = []
    cur: dict = {"flags": "", "line": 1}
    key = None
    for i, line in enumerate(text.splitlines(), 1):
        s = line.strip()
        if not s:
            if cur.get("msgid") is not None:
                entries.append(cur)
            cur, key = {"flags": "", "line": i + 1}, None
            continue
        if s.startswith("#~"):
            cur["obsolete"] = True
            continue
        if s.startswith("#,"):
            cur["flags"] += s[2:]
            continue
        if s.startswith("#"):
            continue
        m = re.match(r'(msgctxt|msgid_plural|msgid|msgstr(?:\[\d+\])?)\s+(".*")$', s)
        if m:
            if m.group(1) in ("msgctxt", "msgid") and cur.get("msgstr") is not None and key and key.startswith("msgstr"):
                entries.append(cur)
                cur = {"flags": "", "line": i}
            key = m.group(1)
            cur[key] = _po_unquote(m.group(2))
            if key.startswith("msgstr"):
                cur["msgstr"] = cur.get("msgstr", "")
            continue
        if s.startswith('"') and key:
            cur[key] = cur.get(key, "") + _po_unquote(s)
    if cur.get("msgid") is not None:
        entries.append(cur)

    target = ""
    src_hint = ""
    for e in entries:
        if e.get("msgid") == "" and "msgctxt" not in e:
            hdr = e.get("msgstr", "")
            m = re.search(r"^Language:\s*(\S+)", hdr, re.M)
            target = m.group(1) if m else ""
            m = re.search(r"^X-Source-Language:\s*(\S+)", hdr, re.M)
            src_hint = m.group(1) if m else ""
    src = source_lang or src_hint
    if not target:
        raise Unsupported("a PO file with no \"Language:\" header. Add the target language to its header, "
                          "or say which language the translations are in.")
    if not src:
        raise NeedsInput("source-lang", "PO files do not say which language the msgid text is in. "
                         "Pass --source-lang (for example en-US).")
    for e in entries:
        if e.get("msgid") in (None, ""):
            continue
        where = f"line {e['line']}"
        if e.get("obsolete"):
            log.exclude(name, where, "TM", target, e["msgid"], "", "Obsolete entry (#~)")
            continue
        if "fuzzy" in e["flags"]:
            log.exclude(name, where, "TM", target, e["msgid"], e.get("msgstr[0]", e.get("msgstr", "")),
                        "Fuzzy: the translator marked it as unchecked")
            continue
        if "msgctxt" in e:
            log.drop_field(name, "PO msgctxt (context)", e["msgctxt"])
        if "msgid_plural" in e:
            pairs = [(e["msgid"], e.get("msgstr[0]", "")), (e["msgid_plural"], e.get("msgstr[1]", ""))]
            extra = [k for k in e if re.fullmatch(r"msgstr\[[2-9]\]", k)]
            if extra:
                log.drop_field(name, "PO extra plural forms (msgstr[2+])", e[extra[0]])
        else:
            pairs = [(e["msgid"], e.get("msgstr", ""))]
        for s_text, t_text in pairs:
            if not t_text.strip():
                log.exclude(name, where, "TM", target, s_text, "", "Not translated (empty msgstr)")
                continue
            out.tm_rows.append(TmRow(src, s_text, target, t_text, where))
    return out


class NeedsInput(Exception):
    def __init__(self, option: str, message: str):
        super().__init__(message)
        self.option = option


# --------------------------------------------------------------------------- TBX

_CONCEPT_LEVEL = {"domain", "subdomains", "definition", "concept_note", "url", "dnt",
                  "translatable", "tags", "note"}


def _assign_concept(c: Concept, label: str, value: str, name: str, log: Log) -> None:
    if not value:
        return
    f = field_of(label)
    if f == "note":
        f = "concept_note"
    if f in ("dnt", "translatable"):
        b = to_bool(value)
        if b is not None:
            c.dnt = b if f == "dnt" else not b
            return
    if f in _CONCEPT_LEVEL and f not in ("dnt", "translatable"):
        if f == "tags":
            c.extra.append(("Tags", value))
        elif c.fields.get(f):
            c.extra.append((label, value))
        else:
            c.fields[f] = value
        return
    if is_admin(label):
        log.drop_field(name, label, value)
        return
    c.extra.append((label, value))


def _assign_term(t: Term, label: str, value: str, name: str, log: Log) -> None:
    if not value:
        return
    f = field_of(label)
    if label in ("administrativeStatus", "normativeAuthorization", "usageStatus", "x-status",
                 "processStatus"):
        f = "status"
    if f in ("dnt", "translatable"):
        b = to_bool(value)
        if b is not None:
            t.dnt = b if f == "dnt" else not b
            return
    if f == "definition":
        # A term has no definition of its own: kept, labelled, in its note.
        t.extra.append(("Definition", value))
        return
    if f in ("status", "forbidden", "preferred", "case_sensitive", "exact_match", "note", "usage",
             "short_form", "term_type", "part_of_speech", "gender", "number"):
        if f == "status" and t.fields.get(f):
            t.fields[f] += f"; {value}"
        elif t.fields.get(f):
            t.extra.append((label, value))
        else:
            t.fields[f] = value
        return
    if is_admin(label):
        log.drop_field(name, label, value)
        return
    t.extra.append((label, value))


def read_tbx(path: str, name: str, log: Log) -> Parsed:
    out = Parsed(name, "tbx", "terms", tool="TBX", kind_reason="TBX is a terminology format")
    root = ET.parse(path).getroot()
    n = 0
    for entry in root.iter():
        if _local(entry.tag) not in ("termEntry", "conceptEntry"):
            continue
        n += 1
        c = Concept(where=f"concept {entry.get('id') or n}", id=entry.get("id") or "")
        _tbx_container(entry, c, None, name, log)
        out.concepts.append(c)
    if not n:
        raise Unsupported("a TBX file with no <termEntry> or <conceptEntry> elements.")
    return out


def _tbx_meta(el: ET.Element) -> tuple[str, str] | None:
    """(label, value) of a data-category element: descrip/termNote/note/admin/xref."""
    tag = _local(el.tag)
    if tag in ("descrip", "termNote", "admin"):
        return el.get("type") or tag, _plain(el)
    if tag == "note":
        return "note", _plain(el)
    if tag in ("xref", "ref"):
        return (el.get("type") or "url"), (el.get("target") or _plain(el))
    if tag == "transacGrp":
        return "transac", _plain(el)
    return None


def _tbx_container(el: ET.Element, c: Concept, lang: str | None, name: str, log: Log) -> None:
    for ch in el:
        tag = _local(ch.tag)
        if tag in ("langSet", "langSec"):
            _tbx_container(ch, c, ch.get(XML_LANG) or ch.get("lang") or "", name, log)
        elif tag in ("tig", "termSec", "ntig"):
            _tbx_term(ch, c, lang or "", name, log)
        elif tag in ("descripGrp", "adminGrp"):
            _tbx_container(ch, c, lang, name, log)
        else:
            meta = _tbx_meta(ch)
            if not meta:
                continue
            label, value = meta
            if label == "transac":
                log.drop_field(name, "TBX transaction (created/modified)", value)
            elif lang:
                # Language-level information: belongs to the concept, labelled with its language.
                if field_of(label) == "definition" and not c.fields.get("definition"):
                    c.fields["definition"] = value
                else:
                    _assign_concept(c, f"{label} ({lang})" if field_of(label) not in ("dnt", "translatable") else label,
                                    value, name, log)
            else:
                _assign_concept(c, label, value, name, log)


def _tbx_term(el: ET.Element, c: Concept, lang: str, name: str, log: Log) -> None:
    t = Term(lang=lang, text="", where=c.where)
    for node in el.iter():
        if node is el:
            continue
        tag = _local(node.tag)
        if tag == "term":
            t.text = t.text or _plain(node)
            continue
        meta = _tbx_meta(node)
        if not meta:
            continue
        label, value = meta
        if label == "transac":
            log.drop_field(name, "TBX transaction (created/modified)", value)
        else:
            _assign_term(t, label, value, name, log)
    if t.text:
        c.terms.append(t)


# --------------------------------------------------------------------- MultiTerm


def read_multiterm(path: str, name: str, log: Log) -> Parsed:
    out = Parsed(name, "multiterm", "terms", tool="MultiTerm", kind_reason="MultiTerm XML is a term base export")
    root = ET.parse(path).getroot()
    n = 0
    for cg in root:
        if _local(cg.tag) != "conceptGrp":
            continue
        n += 1
        c = Concept(where=f"concept {n}")
        for ch in cg:
            tag = _local(ch.tag)
            if tag == "concept":
                c.id = (ch.text or "").strip()
                c.where = f"concept {c.id or n}"
            elif tag == "descripGrp":
                _mt_descrips(ch, lambda label, value: _assign_concept(c, label, value, name, log))
            elif tag == "transacGrp":
                log.drop_field(name, "MultiTerm transaction (created/modified)", _plain(ch))
            elif tag == "system":
                log.drop_field(name, f"MultiTerm system field ({ch.get('type', '')})", _plain(ch))
            elif tag == "languageGrp":
                lang_el = next((x for x in ch if _local(x.tag) == "language"), None)
                lang = ""
                if lang_el is not None:
                    lang = lang_el.get("lang") or lang_el.get("type") or ""
                for sub in ch:
                    st = _local(sub.tag)
                    if st == "descripGrp":
                        _mt_descrips(sub, lambda label, value: _assign_concept(
                            c, f"{label} ({lang})" if field_of(label) != "definition" or c.fields.get("definition") else label,
                            value, name, log))
                    elif st == "termGrp":
                        t = Term(lang=lang, text="", where=c.where)
                        for x in sub:
                            xt = _local(x.tag)
                            if xt == "term":
                                t.text = _plain(x)
                            elif xt == "descripGrp":
                                _mt_descrips(x, lambda label, value: _assign_term(t, label, value, name, log))
                            elif xt == "transacGrp":
                                log.drop_field(name, "MultiTerm transaction (created/modified)", _plain(x))
                        if t.text:
                            c.terms.append(t)
        out.concepts.append(c)
    if not n:
        raise Unsupported("a MultiTerm XML file with no <conceptGrp> entries.")
    return out


def _mt_descrips(grp: ET.Element, put) -> None:
    for d in grp.iter():
        if _local(d.tag) == "descrip":
            put(d.get("type") or "descrip", _plain(d))
        elif _local(d.tag) == "xref":
            put("url", d.get("Tlink") or d.get("target") or _plain(d))
