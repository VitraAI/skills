"""Read and write .xlsx workbooks with the Python standard library only.

Enough of SpreadsheetML for exchange files: cell text, several sheets, a bold
frozen header row. Values are always written as text, so a cell that starts
with "=" or looks like a date stays exactly what the source said.
"""

from __future__ import annotations

import re
import zipfile
from typing import Iterable, Iterator
from xml.etree import ElementTree as ET

MAIN_NS = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
PKG_REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"

# Excel refuses a longer cell; it truncates on open and save.
MAX_CELL_CHARS = 32767

_INVALID_XML = re.compile("[\x00-\x08\x0b\x0c\x0e-\x1f￾￿]")
_ESCAPED_CHAR = re.compile(r"_x([0-9A-Fa-f]{4})_")


def strip_invalid_xml(text: str) -> str:
    return _INVALID_XML.sub("", text)


def has_invalid_xml(text: str) -> bool:
    return bool(_INVALID_XML.search(text))


# --------------------------------------------------------------------------- read


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _col_index(ref: str) -> int:
    n = 0
    for ch in ref:
        if "A" <= ch <= "Z":
            n = n * 26 + (ord(ch) - 64)
        elif "a" <= ch <= "z":
            n = n * 26 + (ord(ch) - 96)
        else:
            break
    return n - 1


def _unescape(text: str) -> str:
    # Excel writes control characters (and a literal "_x" run) as _xHHHH_.
    return _ESCAPED_CHAR.sub(lambda m: chr(int(m.group(1), 16)), text)


def _rich_text(el: ET.Element) -> str:
    """Text of an <si> / <is>: plain <t>, or the runs of <r><t>; phonetic <rPh> skipped."""
    parts: list[str] = []
    for child in el:
        name = _local(child.tag)
        if name == "t":
            parts.append(child.text or "")
        elif name == "r":
            for t in child:
                if _local(t.tag) == "t":
                    parts.append(t.text or "")
    return _unescape("".join(parts))


class XlsxReader:
    """Lazy reader: sheet names first, rows of one sheet on demand."""

    def __init__(self, path: str):
        self.zip = zipfile.ZipFile(path)
        names = set(self.zip.namelist())
        if "xl/workbook.xml" not in names:
            raise ValueError("not an .xlsx workbook (no xl/workbook.xml)")
        self._strings: list[str] | None = None
        rels = {}
        rels_path = "xl/_rels/workbook.xml.rels"
        if rels_path in names:
            for rel in ET.fromstring(self.zip.read(rels_path)):
                target = rel.get("Target", "")
                target = target.lstrip("/")
                if not target.startswith("xl/"):
                    target = "xl/" + target
                rels[rel.get("Id")] = target
        self.sheets: list[tuple[str, str]] = []
        wb = ET.fromstring(self.zip.read("xl/workbook.xml"))
        for el in wb.iter():
            if _local(el.tag) == "sheet":
                rid = el.get(f"{{{REL_NS}}}id")
                target = rels.get(rid)
                if target and target in names:
                    self.sheets.append((el.get("name", ""), target))

    @property
    def sheet_names(self) -> list[str]:
        return [n for n, _ in self.sheets]

    def _shared(self) -> list[str]:
        if self._strings is None:
            self._strings = []
            if "xl/sharedStrings.xml" in self.zip.namelist():
                with self.zip.open("xl/sharedStrings.xml") as fh:
                    for _, el in ET.iterparse(fh, events=("end",)):
                        if _local(el.tag) == "si":
                            self._strings.append(_rich_text(el))
                            el.clear()
        return self._strings

    def rows(self, sheet: str | int = 0) -> Iterator[list[str]]:
        """Each row as a list of strings, gaps filled with ""; fully blank rows skipped."""
        if isinstance(sheet, int):
            target = self.sheets[sheet][1]
        else:
            target = dict(self.sheets)[sheet]
        strings = self._shared()
        with self.zip.open(target) as fh:
            for _, el in ET.iterparse(fh, events=("end",)):
                if _local(el.tag) != "row":
                    continue
                cells: dict[int, str] = {}
                nxt = 0
                for c in el:
                    if _local(c.tag) != "c":
                        continue
                    ref = c.get("r")
                    idx = _col_index(ref) if ref else nxt
                    nxt = idx + 1
                    kind = c.get("t", "n")
                    value = ""
                    if kind == "inlineStr":
                        for k in c:
                            if _local(k.tag) == "is":
                                value = _rich_text(k)
                    else:
                        v = next((k for k in c if _local(k.tag) == "v"), None)
                        raw = v.text if v is not None and v.text is not None else ""
                        if kind == "s" and raw:
                            i = int(raw)
                            value = strings[i] if 0 <= i < len(strings) else ""
                        elif kind == "b":
                            value = "TRUE" if raw == "1" else "FALSE" if raw else ""
                        elif kind in ("str", "e"):
                            value = _unescape(raw)
                        else:
                            value = _number_text(raw)
                    cells[idx] = value
                el.clear()
                if not any(v.strip() for v in cells.values()):
                    continue
                width = max(cells) + 1
                yield [cells.get(i, "") for i in range(width)]

    def close(self) -> None:
        self.zip.close()


def _number_text(raw: str) -> str:
    if not raw:
        return ""
    try:
        f = float(raw)
    except ValueError:
        return raw
    if f.is_integer() and "e" not in raw.lower():
        return str(int(f))
    return raw


# -------------------------------------------------------------------------- write


def _esc(text: str) -> str:
    # A literal "_x0041_" in the text would be read back as "A": escape its "_".
    text = _ESCAPED_CHAR.sub(lambda m: "_x005F" + m.group(0), strip_invalid_xml(text))
    return (
        text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _col_name(i: int) -> str:
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


_CONTENT_TYPES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
    '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
    '<Default Extension="xml" ContentType="application/xml"/>'
    '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
    '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'
    "{sheets}</Types>"
)
_SHEET_TYPE = (
    '<Override PartName="/xl/worksheets/sheet{n}.xml" '
    'ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>'
)
_ROOT_RELS = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<Relationships xmlns="{PKG_REL_NS}">'
    '<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>'
    "</Relationships>"
)
_STYLES = (
    '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
    f'<styleSheet xmlns="{MAIN_NS}">'
    '<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font>'
    '<font><b/><sz val="11"/><name val="Calibri"/></font></fonts>'
    '<fills count="2"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill></fills>'
    '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
    '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
    '<cellXfs count="3"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
    '<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>'
    '<xf numFmtId="49" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/></cellXfs>'
    "</styleSheet>"
)


def _sheet_name(name: str, used: set[str]) -> str:
    clean = re.sub(r"[\[\]:*?/\\]", " ", name).strip() or "Sheet"
    clean = clean[:31]
    base, n = clean, 2
    while clean.lower() in used:
        suffix = f" ({n})"
        clean = base[: 31 - len(suffix)] + suffix
        n += 1
    used.add(clean.lower())
    return clean


def write_xlsx(path: str, sheets: list[tuple[str, list[str], Iterable[list[str]]]]) -> None:
    """Write sheets of (name, header, rows). Every cell is a text cell."""
    used: set[str] = set()
    names = [_sheet_name(n, used) for n, _, _ in sheets]
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as z:
        z.writestr(
            "[Content_Types].xml",
            _CONTENT_TYPES.format(
                sheets="".join(_SHEET_TYPE.format(n=i + 1) for i in range(len(sheets)))
            ),
        )
        z.writestr("_rels/.rels", _ROOT_RELS)
        z.writestr("xl/styles.xml", _STYLES)
        z.writestr(
            "xl/workbook.xml",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<workbook xmlns="{MAIN_NS}" xmlns:r="{REL_NS}"><sheets>'
            + "".join(
                f'<sheet name="{_esc(n)}" sheetId="{i + 1}" r:id="rId{i + 1}"/>'
                for i, n in enumerate(names)
            )
            + "</sheets></workbook>",
        )
        z.writestr(
            "xl/_rels/workbook.xml.rels",
            '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<Relationships xmlns="{PKG_REL_NS}">'
            + "".join(
                f'<Relationship Id="rId{i + 1}" '
                'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" '
                f'Target="worksheets/sheet{i + 1}.xml"/>'
                for i in range(len(sheets))
            )
            + f'<Relationship Id="rId{len(sheets) + 1}" '
            'Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" '
            'Target="styles.xml"/></Relationships>',
        )
        for i, (_, header, rows) in enumerate(sheets):
            with z.open(f"xl/worksheets/sheet{i + 1}.xml", "w") as fh:
                _write_sheet(fh, header, rows)


def _write_sheet(fh, header: list[str], rows: Iterable[list[str]]) -> None:
    def put(s: str) -> None:
        fh.write(s.encode("utf-8"))

    put('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n')
    put(f'<worksheet xmlns="{MAIN_NS}">')
    put('<sheetViews><sheetView workbookViewId="0"><pane ySplit="1" topLeftCell="A2" '
        'activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>')
    put("<cols>" + "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{_width(h)}" customWidth="1"/>'
        for i, h in enumerate(header)
    ) + "</cols>" if header else "")
    put("<sheetData>")
    r = 1
    put(_row(r, header, style=1))
    buf: list[str] = []
    for row in rows:
        r += 1
        buf.append(_row(r, row, style=2))
        if len(buf) >= 500:
            put("".join(buf))
            buf.clear()
    if buf:
        put("".join(buf))
    put("</sheetData></worksheet>")


def _width(header: str) -> int:
    if header.lower() in ("source text", "target text", "term", "definition", "note", "reason",
                          "source", "target", "description", "value", "example"):
        return 50
    return max(12, min(30, len(header) + 4))


def _row(r: int, values: list[str], style: int) -> str:
    cells = []
    for i, v in enumerate(values):
        if v is None or v == "":
            continue
        text = _esc(str(v))
        cells.append(
            f'<c r="{_col_name(i)}{r}" t="inlineStr" s="{style}"><is><t xml:space="preserve">{text}</t></is></c>'
        )
    return f'<row r="{r}">{"".join(cells)}</row>'
