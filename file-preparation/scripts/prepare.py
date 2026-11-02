#!/usr/bin/env python3
"""Convert translation memories, term bases and glossaries from any tool into
files VitraTM imports, split to fit its per-file limits, with a report of
everything that was kept, changed or left out.

    prepare.py inspect <file or folder>... [options]
    prepare.py convert <file or folder>... --out <folder> [options]

Prints one JSON object. Exit 0 = done, 2 = an answer is needed (see
"needs_input"), 1 = failed. Python 3.10+, standard library only.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import sys
import tempfile
import traceback
import zipfile

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _lang  # noqa: E402
import _readers  # noqa: E402
import _tables  # noqa: E402
import _terms  # noqa: E402
import _tm  # noqa: E402
from _model import (CLAIMED, LIMIT_BYTES, LIMIT_GLOSSARY_ENTRIES, LIMIT_TB_CONCEPTS,  # noqa: E402
                    LIMIT_TM_UNITS, GlossaryEntry, Log, claim)
from _xlsx import write_xlsx  # noqa: E402

READABLE_EXT = {".tmx", ".xlf", ".xliff", ".sdlxliff", ".mqxliff", ".mxliff", ".txlf", ".sdltm", ".po", ".pot",
                ".tbx", ".xml", ".mtf", ".xlsx", ".xlsm", ".csv", ".tsv", ".tab", ".txt", ".zip"}
MAX_ZIP_MEMBER = 1024 * 1024 * 1024


class Options:
    def __init__(self, a):
        self.lang_map = _lang.parse_map(a.lang_map)
        self.source_lang = a.source_lang
        self.target_lang = a.target_lang
        self.as_kind = {"tm": "tm", "termbase": "terms", "term-base": "terms", "terms": "terms",
                        "glossary": "glossary", None: None}[a.as_kind]
        self.dnt = a.dnt
        self.status = a.status
        self.map_spec = None
        if a.map:
            with open(a.map, encoding="utf-8") as fh:
                self.map_spec = json.load(fh)
        for opt in ("source_lang", "target_lang"):
            v = getattr(self, opt)
            if v and not _lang.resolve(v, self.lang_map):
                raise ValueError(f"--{opt.replace('_', '-')}: '{v}' is not a language code Vitra accepts")
            if v:
                setattr(self, opt, _lang.resolve(v, self.lang_map))


# ------------------------------------------------------------------- inputs


def collect(paths: list[str], tmp: str, log: Log) -> list[tuple[str, str]]:
    """(path on disk, display name) of every file to read; folders walked, zips unpacked to tmp."""
    out = []
    for p in paths:
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for f in sorted(files):
                    if f.startswith((".", "~$")):
                        continue
                    full = os.path.join(root, f)
                    rel = os.path.relpath(full, os.path.dirname(os.path.abspath(p)))
                    if os.path.splitext(f)[1].lower() in READABLE_EXT:
                        out.append((full, rel))
                    else:
                        log.note(f"{rel} skipped (not a TM, term base or glossary format)")
        elif os.path.isfile(p):
            out.append((p, os.path.basename(p)))
        else:
            raise FileNotFoundError(f"No such file or folder: {p}")
    final = []
    for path, name in out:
        if zipfile.is_zipfile(path) and os.path.splitext(path)[1].lower() == ".zip":
            with zipfile.ZipFile(path) as z:
                for i, info in enumerate(z.infolist()):
                    member = info.filename
                    if info.is_dir() or os.path.basename(member).startswith((".", "~$")) or "__MACOSX" in member:
                        continue
                    if os.path.splitext(member)[1].lower() not in READABLE_EXT - {".zip"}:
                        log.note(f"{name}: {member} skipped (not a TM, term base or glossary format)")
                        continue
                    if info.file_size > MAX_ZIP_MEMBER:
                        log.note(f"{name}: {member} skipped (larger than 1 GB unpacked)")
                        continue
                    dest_dir = os.path.join(tmp, f"zip{len(final)}_{i}")
                    os.makedirs(dest_dir)
                    dest = os.path.join(dest_dir, os.path.basename(member))
                    with z.open(info) as src, open(dest, "wb") as dst:
                        shutil.copyfileobj(src, dst)
                    final.append((dest, f"{name}/{member}"))
        else:
            final.append((path, name))
    return final


def read_one(path: str, name: str, log: Log, opts: Options) -> list[_readers.Parsed]:
    fmt = _readers.detect(path)
    if fmt == "tmx":
        return [_readers.read_tmx(path, name, log)]
    if fmt == "xliff":
        return [_readers.read_xliff(path, name, log)]
    if fmt == "sdltm":
        return [_readers.read_sdltm(path, name, log)]
    if fmt == "po":
        return [_readers.read_po(path, name, log, opts.source_lang or "")]
    if fmt == "tbx":
        return [_readers.read_tbx(path, name, log)]
    if fmt == "multiterm":
        return [_readers.read_multiterm(path, name, log)]
    if fmt in ("xlsx", "csv"):
        return _tables.read_table(path, fmt, name, log, opts)
    raise _readers.Unsupported(f"an unexpected format ({fmt}).")


# ------------------------------------------------------------------ convert


def safe_base(name: str) -> str:
    base = os.path.splitext(os.path.basename(name.replace(" [", "_").replace("]", "")))[0]
    return re.sub(r"[^\w.\- ()]+", "_", base).strip(" ._") or "converted"


def plan_terms(p: _readers.Parsed, log: Log, opts: Options, resolve) -> dict:
    """Decide term base vs glossary and prepare the records."""
    if p.kind == "glossary" and opts.as_kind in (None, "glossary"):
        entries = _terms.prepare_entries(p.entries, p.file, log, resolve)
        return {"target": "glossary", "why": "The file is a glossary", "entries": entries}
    if p.kind == "glossary":  # --as termbase on a glossary file
        p.concepts = [_entry_to_concept(e) for e in p.entries]
    concepts = _terms.prepare_concepts(p.concepts, p.file, log, resolve)
    dnt = [True if opts.dnt else _terms.is_dnt(c, p.dnt_hint) for c in concepts]
    n_dnt = sum(dnt)
    if opts.as_kind == "glossary":
        target, why = "glossary", "Asked for a glossary (--as glossary)"
    elif opts.as_kind == "terms":
        target, why = "termbase", "Asked for a term base (--as termbase)"
    elif concepts and n_dnt == len(concepts):
        target, why = "glossary", "Every entry is do-not-translate, so it becomes a glossary (Translatable = no)"
    else:
        target, why = "termbase", "Terminology with translations becomes a term base"
        if n_dnt:
            log.note(f"{p.file}: {n_dnt} of {len(concepts)} concepts are do-not-translate; they stay in the "
                     "term base with \"Do not translate.\" in the concept note. Term bases cannot enforce it; "
                     "convert with --as glossary if those must be enforced.")
    if target == "glossary":
        src = _terms.source_language(concepts, opts.source_lang)
        entries = _terms.concepts_to_entries(concepts, dnt, src, p.file, log)
        entries = _terms.prepare_entries(entries, p.file, log, resolve)
        return {"target": "glossary", "why": why, "entries": entries, "dnt": n_dnt}
    return {"target": "termbase", "why": why, "concepts": concepts, "dnt_flags": dnt, "dnt": n_dnt}


def _entry_to_concept(e: GlossaryEntry):
    from _model import Concept, Term
    c = Concept(where=e.where)
    if e.description:
        c.fields["definition"] = e.description
    if e.tags:
        c.fields["domain"] = e.tags[0]
        if e.tags[1:]:
            c.fields["subdomains"] = "; ".join(e.tags[1:])
    c.dnt = (e.translatable is False) or None
    c.terms.append(Term(lang=e.lang, text=e.term, where=e.where,
                        fields={"case_sensitive": "yes"} if e.case_sensitive else {}))
    for lang, text, note in e.translations:
        c.terms.append(Term(lang=lang, text=text, where=e.where, fields={"note": note} if note else {}))
    return c


def run(args) -> tuple[int, dict]:
    opts = Options(args)
    log = Log()
    CLAIMED.clear()
    dry = args.command == "inspect"
    out_dir = None if dry else os.path.abspath(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    result: dict = {"status": "ok", "inputs": [], "outputs": [], "notes": log.notes}
    tmp = tempfile.mkdtemp(prefix="vitra-prep-")
    needs = []
    try:
        files = collect(args.inputs, tmp, log)
        parsed: list[_readers.Parsed] = []
        for path, name in files:
            info = {"file": name}
            try:
                got = read_one(path, name, log, opts)
            except _readers.NeedsInput as e:
                needs.append({"file": name, "option": f"--{e.option}", "question": str(e)})
                result["inputs"].append({**info, "status": "needs_input"})
                continue
            except _readers.Unsupported as e:
                result["inputs"].append({**info, "status": "unsupported", "reason": f"This is {e}"
                                         if not str(e).startswith(("The ", "--")) else str(e)})
                continue
            except Exception as e:  # a broken file must not stop the others
                failed = {**info, "status": "failed", "reason": f"{type(e).__name__}: {e}"}
                if os.environ.get("VITRA_PREP_DEBUG"):
                    failed["trace"] = traceback.format_exc()
                result["inputs"].append(failed)
                continue
            parsed.extend(got)

        if args.merge and parsed:
            parsed = _merge(parsed, args.name or "merged")

        for p in parsed:
            resolve = _tm.Resolver(opts.lang_map)
            base = safe_base(args.name if args.name and (args.merge or len(parsed) == 1) else p.file)
            entry = {"file": p.file, "status": "read", "format": p.format, "tool": p.tool,
                     "content": {"tm": "translation memory", "terms": "terminology",
                                 "glossary": "glossary"}[p.kind],
                     "why": p.kind_reason, "certain": p.confident}
            if p.mapping:
                entry["column_map"] = p.mapping
            if p.kind == "tm":
                if opts.as_kind in ("terms", "glossary"):
                    entry["warning"] = "--as only changes terminology output; this file was read as a memory."
                units = _tm.build_units(p.tm_rows, p.file, log, resolve, opts.status)
                entry.update(becomes="translation memory", units=len(units),
                             translations=sum(len(t) for _, _, t in units),
                             files_needed=-(-len(units) // args.max_units) if units else 0)
                if not dry and units:
                    result["outputs"] += _tm.write_units(units, out_dir, base, args.max_units, args.max_bytes)
            else:
                plan = plan_terms(p, log, opts, resolve)
                entry.update(becomes={"glossary": "glossary", "termbase": "term base"}[plan["target"]],
                             why_this_output=plan["why"], do_not_translate=plan.get("dnt", 0))
                if plan["target"] == "glossary":
                    entry.update(entries=len(plan["entries"]),
                                 files_needed=-(-len(plan["entries"]) // args.max_entries) if plan["entries"] else 0)
                    if not dry and plan["entries"]:
                        result["outputs"] += _terms.write_glossary(plan["entries"], out_dir, base,
                                                                   args.max_entries, args.max_bytes)
                else:
                    rows = _terms.tb_rows(plan["concepts"], plan["dnt_flags"], p.file, log)
                    entry.update(concepts=len(rows), terms=sum(len(r) for _, r in rows),
                                 files_needed=-(-len(rows) // args.max_concepts) if rows else 0)
                    if not dry and rows:
                        result["outputs"] += _terms.write_term_base(rows, out_dir, base, log, p.file,
                                                                    args.max_concepts, args.max_bytes)
            entry["languages"] = {raw: (code or "NOT IN VITRA'S LIST") for raw, code in resolve.seen.items()}
            result["inputs"].append(entry)

        result["excluded"] = len(log.excluded)
        result["changed"] = len(log.changed)
        result["not_imported_fields"] = [
            {"file": f, "field": k, "count": v[0], "example": v[1]} for (f, k), v in log.not_imported.items()]
        if needs:
            result["status"] = "needs_input"
            result["needs_input"] = needs
        if not dry and (result["outputs"] or log.excluded or log.changed):
            stem = (safe_base(args.name) if args.name else
                    safe_base(files[0][1]) if len(files) == 1 else "")
            report = claim(os.path.join(out_dir, (stem + " - " if stem else "") + "conversion report.xlsx"))
            write_report(report, result, log)
            result["report"] = report
        if dry:
            result["excluded_examples"] = [dict(zip(["file", "where", "kind", "language", "text", "translation",
                                                     "reason"], r)) for r in log.excluded[:10]]
            result["reasons"] = _reason_counts(log)
        return (2 if needs else 0), result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _merge(parsed: list[_readers.Parsed], name: str) -> list[_readers.Parsed]:
    """--merge: every memory into one, every terminology file into one."""
    out = []
    for kind in ("tm", "terms", "glossary"):
        group = [p for p in parsed if p.kind == kind]
        if not group:
            continue
        m = _readers.Parsed(name, "+".join(sorted({p.format for p in group})), kind,
                            kind_reason=f"{len(group)} files merged", confident=all(p.confident for p in group),
                            dnt_hint=all(p.dnt_hint for p in group))
        for p in group:
            m.tm_rows += p.tm_rows
            m.concepts += p.concepts
            m.entries += p.entries
        out.append(m)
    return out


def _reason_counts(log: Log) -> dict:
    counts: dict[str, int] = {}
    for r in log.excluded:
        reason = re.sub(r"\(.*|: .*", "", r[6]).strip()
        counts[reason] = counts.get(reason, 0) + 1
    return counts


def write_report(path: str, result: dict, log: Log) -> None:
    summary = []
    for i in result["inputs"]:
        summary.append([i["file"], i.get("status", ""), i.get("format", ""), i.get("tool", ""),
                        i.get("content", ""), i.get("becomes", ""), i.get("why_this_output", i.get("why", "")),
                        str(i.get("units", i.get("concepts", i.get("entries", "")))),
                        ", ".join(f"{k} → {v}" for k, v in (i.get("languages") or {}).items()),
                        i.get("reason", "")])
    outputs = [[os.path.basename(o["file"]), o["import_into"],
                str(o.get("units", o.get("concepts", o.get("entries", "")))), str(o.get("rows", "")),
                ", ".join(o.get("source_languages", []) + o.get("target_languages", []) or o.get("languages", [])),
                f"{o['bytes'] / 1024 / 1024:.1f} MB"] for o in result["outputs"]]
    reasons = [[k, str(v)] for k, v in sorted(_reason_counts(log).items(), key=lambda kv: -kv[1])]
    fields = [[f, k, str(v[0]), v[1]] for (f, k), v in log.not_imported.items()]
    cap = 500_000
    write_xlsx(path, [
        ("Summary", ["Input", "Status", "Format", "Tool", "Content", "Becomes", "Why", "Units / concepts / entries",
                     "Languages (as written → Vitra code)", "Problem"], summary),
        ("Output files", ["File", "Import into", "Units / concepts / entries", "Rows", "Languages", "Size"], outputs),
        ("Left out - totals", ["Reason", "Count"], reasons),
        ("Left out", ["Input", "Where", "What", "Language", "Text", "Translation", "Reason"], log.excluded[:cap]),
        ("Changed", ["Input", "Where", "What", "Before", "After", "Why"], log.changed[:cap]),
        ("Value mapping", ["Input", "Column", "Value in the file", "Imported as", "Times"],
         [[f, c, b, a, str(n)] for (f, c, b, a), n in sorted(log.values.items(), key=lambda kv: -kv[1])]),
        ("Not imported fields", ["Input", "Field", "Values", "Example"], fields),
        ("Notes", ["Note"], [[n] for n in log.notes]),
    ])


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("command", choices=["inspect", "convert"])
    ap.add_argument("inputs", nargs="+", help="files, folders or .zip archives")
    ap.add_argument("--out", help="folder for the converted files and the report (convert)")
    ap.add_argument("--name", help="base name for the output files")
    ap.add_argument("--merge", action="store_true", help="merge all memories into one, all terminology into one")
    ap.add_argument("--as", dest="as_kind", choices=["tm", "termbase", "term-base", "terms", "glossary"],
                    help="force the output for terminology files")
    ap.add_argument("--dnt", action="store_true", help="treat every term as do-not-translate")
    ap.add_argument("--status", choices=["unverified", "verified", "approved"],
                    help="TM status for translations whose file gives none")
    ap.add_argument("--source-lang", help="source language when the file does not say (e.g. en-US)")
    ap.add_argument("--target-lang", help="target language when the file does not say")
    ap.add_argument("--lang-map", action="append", metavar="FROM=TO",
                    help="map a language as written to a Vitra code; repeatable")
    ap.add_argument("--map", help="JSON column map for a spreadsheet layout that was not recognized")
    ap.add_argument("--max-units", type=int, default=LIMIT_TM_UNITS)
    ap.add_argument("--max-concepts", type=int, default=LIMIT_TB_CONCEPTS)
    ap.add_argument("--max-entries", type=int, default=LIMIT_GLOSSARY_ENTRIES)
    ap.add_argument("--max-mb", type=float, default=24.0, help="largest output file in MB (VitraTM's cap is 25)")
    args = ap.parse_args(argv)
    args.max_units = max(1, min(args.max_units, LIMIT_TM_UNITS))
    args.max_concepts = max(1, min(args.max_concepts, LIMIT_TB_CONCEPTS))
    args.max_entries = max(1, min(args.max_entries, LIMIT_GLOSSARY_ENTRIES))
    args.max_bytes = int(min(args.max_mb * 1024 * 1024, LIMIT_BYTES))
    if args.command == "convert" and not args.out:
        ap.error("convert needs --out <folder>")
    try:
        code, result = run(args)
    except Exception as e:  # noqa: BLE001
        result = {"status": "failed", "error": f"{type(e).__name__}: {e}"}
        if os.environ.get("VITRA_PREP_DEBUG"):
            result["trace"] = traceback.format_exc()
        code = 1
    print(json.dumps(result, ensure_ascii=False, indent=1))
    return code


if __name__ == "__main__":
    sys.exit(main())
