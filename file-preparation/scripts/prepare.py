#!/usr/bin/env python3
"""Convert translation memories, term bases and glossaries from any tool into
files VitraTM imports, split to fit its per-file limits, with a report of
everything that was kept, changed or left out, and of the problems found in
the client's data.

    prepare.py inspect <file or folder>... [options]   read only: what each file is, the
                                                       questions to ask, the problems found
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
from collections import Counter

sys.dont_write_bytecode = True
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import _checks  # noqa: E402
import _lang  # noqa: E402
import _readers  # noqa: E402
import _tables  # noqa: E402
import _terms  # noqa: E402
import _tm  # noqa: E402
from _model import (CLAIMED, LIMIT_BYTES, LIMIT_GLOSSARY_ENTRIES, LIMIT_TB_CONCEPTS,  # noqa: E402
                    LIMIT_TM_UNITS, GlossaryEntry, Log, claim, fold_key)
from _xlsx import Styled, write_xlsx  # noqa: E402

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
        self.status = None if a.status in (None, "none") else a.status
        self.term_status = None if a.term_status in (None, "none") else a.term_status
        self.keep_tags = a.tags != "drop"
        self.merge_tm = a.merge or a.merge_tm == "yes"
        self.merge_terms = a.merge or a.merge_terms == "yes"
        self.join = a.join_duplicates == "yes"
        self.rule = a.conflicts or "frequent"
        self.fix_spaces = a.fix_spaces == "yes"
        self.split_alternatives = a.split_alternatives == "yes"
        self.dnt_lists = a.dnt_lists or "glossary"
        # Questions the user has answered already (an option given on the command line).
        self.answered = {
            "merge_tm": a.merge or a.merge_tm is not None,
            "merge_terms": a.merge or a.merge_terms is not None,
            "join_duplicates": a.join_duplicates is not None,
            "conflicts": a.conflicts is not None,
            "status": a.status is not None,
            "term_status": a.term_status is not None,
            "tags": a.tags is not None,
            "fix_spaces": a.fix_spaces is not None,
            "split_alternatives": a.split_alternatives is not None,
            "dnt_lists": a.dnt_lists is not None or a.as_kind is not None,
        }
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
        return [_readers.read_tmx(path, name, log, opts.keep_tags)]
    if fmt == "xliff":
        return [_readers.read_xliff(path, name, log, opts.keep_tags)]
    if fmt == "sdltm":
        return [_readers.read_sdltm(path, name, log, opts.keep_tags)]
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


def _group_name(files: list[str]) -> str:
    """A merged output's name: what its inputs' names share, minus trailing language codes."""
    bases = [safe_base(f) for f in files]
    prefix = os.path.commonprefix(bases)
    prefix = re.sub(r"([-_ .]*[A-Za-z]{2,3}[-_][A-Za-z]{2,4})+[-_ .]*$", "", prefix)
    prefix = re.sub(r"[-_ .(]+$", "", prefix)
    return prefix if len(prefix) >= 3 else "merged"


class Group:
    """One output: a memory, a term base or a glossary, made from one input file or several."""

    def __init__(self, kind: str, members: list[_readers.Parsed], name: str):
        self.kind = kind
        self.members = members
        self.name = name

    @property
    def label(self) -> str:
        return self.members[0].file if len(self.members) == 1 else self.name


def make_groups(parsed: list[_readers.Parsed], opts: Options, name: str | None) -> list[Group]:
    groups: list[Group] = []
    tm = [p for p in parsed if p.kind == "tm"]
    terms = [p for p in parsed if p.kind == "terms"]
    gl = [p for p in parsed if p.kind == "glossary"]
    if opts.merge_tm and len(tm) > 1:
        groups.append(Group("tm", tm, name or _group_name([p.file for p in tm])))
    else:
        groups += [Group("tm", [p], p.file) for p in tm]
    if opts.merge_terms and len(terms) > 1:
        # Do-not-translate lists and translated term lists stay apart: one glossary, one term base.
        for dnt in (False, True):
            part = [p for p in terms if p.dnt_list == dnt]
            if part:
                groups.append(Group("terms", part, name or _group_name([p.file for p in part])))
    else:
        groups += [Group("terms", [p], p.file) for p in terms]
    if opts.merge_terms and len(gl) > 1:
        groups.append(Group("glossary", gl, name or _group_name([p.file for p in gl])))
    else:
        groups += [Group("glossary", [p], p.file) for p in gl]
    return groups


def plan_terms(concepts, dnt_list: bool, dnt_hint: bool, label: str, log: Log, opts: Options, src: str) -> dict:
    """Decide term base vs glossary and prepare the records."""
    implied = [True if opts.dnt else _terms.is_dnt(c, dnt_hint) for c in concepts]
    listed = sum(implied)  # as the client listed them, before the one-language rule below
    targets = {t.lang for c in concepts for t in c.terms if t.lang != src}
    if dnt_list and len(targets) > 1 and not opts.dnt:
        # Per-language do-not-translate lists merged: an entry listed for SOME languages only.
        # A glossary entry with Translatable = no applies in every language, so it stays
        # translatable, kept as is in the languages that list it.
        for i, c in enumerate(concepts):
            have = {t.lang for t in c.terms if t.lang != src}
            if implied[i] and have and have != targets:
                implied[i] = False
                s_text = next((t.text for t in c.terms if t.lang == src), c.terms[0].text)
                log.issue(label, c.where, "Glossary", "Do-not-translate in some languages only", s_text,
                          "Listed only for " + ", ".join(sorted(have)),
                          "A translatable entry that keeps the source text in " + ", ".join(sorted(have)) +
                          " (Translatable = no would apply to every language)", "check")
    n, n_dnt = len(concepts), sum(implied)
    mixed = False
    if opts.as_kind == "glossary":
        target, why = "glossary", "You chose a glossary (--as glossary)"
    elif opts.as_kind == "terms":
        target, why = "termbase", "You chose a term base (--as termbase)"
    elif concepts and n_dnt == n:
        target, why = "glossary", "Every entry keeps its source text (do-not-translate), so it becomes a glossary " \
                                  "where Translatable = no, which Vitra enforces"
    elif dnt_list and listed * 2 > n and opts.dnt_lists == "glossary":
        target, mixed = "glossary", True
        why = (f"A do-not-translate list: {n_dnt} of {n} entries keep their source text in every language "
               f"(Translatable = no); the other {n - n_dnt} are translated, or listed for some languages only, "
               "so they stay translatable with the text the list gives")
    else:
        target, why = "termbase", "Terminology with translations becomes a term base"
        if dnt_list and n_dnt and opts.dnt_lists == "termbase":
            why = "You chose a term base for do-not-translate lists"
    if target == "glossary":
        entries = _terms.concepts_to_entries(concepts, implied, src, label, log)
        if mixed:
            for c, d in zip(concepts, implied):
                if not d:
                    _checks.check_glossary_routing(c, src, label, log)
        entries = _terms.prepare_entries(entries, label, log, _tm.Resolver(opts.lang_map))
        return {"target": "glossary", "why": why, "entries": entries, "dnt": n_dnt, "mixed": mixed}
    flags = [True if opts.dnt else _terms.is_dnt(c, dnt_hint, explicit_only=True) for c in concepts]
    if sum(flags):
        log.note(f"{label}: {sum(flags)} of {n} concepts are marked do-not-translate; they stay in the "
                 "term base with \"Do not translate.\" in the concept note. Term bases cannot enforce it; "
                 "convert with --as glossary if those must be enforced.")
    return {"target": "termbase", "why": why, "concepts": concepts, "dnt_flags": flags, "dnt": sum(flags)}


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




def _input_entry(p: _readers.Parsed, resolve: _tm.Resolver) -> dict:
    entry = {"file": p.file, "status": "read", "format": p.format, "tool": p.tool,
             "content": {"tm": "translation memory", "terms": "terminology", "glossary": "glossary"}[p.kind],
             "why": p.kind_reason, "certain": p.confident}
    if p.mapping:
        entry["column_map"] = p.mapping
    if p.kind == "tm":
        for r in p.tm_rows:
            resolve(r.src_lang)
            resolve(r.tgt_lang)
        entry["rows_read"] = len(p.tm_rows)
        if p.tags_found:
            entry["inline_tags"] = p.tags_found
    elif p.kind == "terms":
        entry["concepts_read"] = len(p.concepts)
        entry["terms_read"] = sum(len(c.terms) for c in p.concepts)
    else:
        for e in p.entries:
            resolve(e.lang)
            for lang, _, _ in e.translations:
                resolve(lang)
        entry["entries_read"] = len(p.entries)
    if p.dnt_list:
        entry["says_do_not_translate"] = True
    return entry


def run(args) -> tuple[int, dict]:
    opts = Options(args)
    log = Log()
    CLAIMED.clear()
    dry = args.command == "inspect"
    out_dir = None if dry else os.path.abspath(args.out)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)
    result: dict = {"status": "ok", "inputs": [], "plan": [], "outputs": [], "notes": log.notes}
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

        # Per input: languages resolved, terminology cleaned, what was read.
        by_file: dict[str, dict] = {}
        for p in parsed:
            p.dnt_list = bool(_tables._DNT_HINT.search(os.path.basename(p.file)))
            if p.kind == "glossary" and opts.as_kind == "terms":
                p.concepts = [_entry_to_concept(e) for e in p.entries]
                p.kind = "terms"
            resolve = _tm.Resolver(opts.lang_map)
            if p.kind == "terms":
                p.concepts = _terms.prepare_concepts(p.concepts, p.file, log, resolve, opts.fix_spaces)
            entry = _input_entry(p, resolve)
            if p.kind == "tm" and opts.as_kind in ("terms", "glossary"):
                entry["warning"] = "--as only changes terminology output; this file was read as a memory."
            entry["languages"] = {raw: (code or "NOT IN VITRA'S LIST") for raw, code in resolve.seen.items() if raw}
            by_file[p.file] = entry
            result["inputs"].append(entry)

        groups = make_groups(parsed, opts, args.name)
        tb_for_check, gl_for_check = [], []
        stats = Counter()
        for g in groups:
            base = safe_base(args.name if args.name and len(groups) == 1 else g.name)
            plan = {"output": g.label, "from": [p.file for p in g.members]}
            if g.kind == "tm":
                rows = [r for p in g.members for r in p.tm_rows]
                stats["tm_rows_without_status"] += sum(1 for r in rows if not r.status)
                stats["inline_tags"] += sum(p.tags_found for p in g.members)
                units = _tm.build_units(rows, g.label, log, _tm.Resolver(opts.lang_map), opts.status, opts.rule)
                _checks.check_units(units, g.label, log)
                plan.update(becomes="translation memory", units=len(units),
                            translations=sum(len(t) for _, _, t in units),
                            files_needed=-(-len(units) // args.max_units) if units else 0)
                if not dry and units:
                    result["outputs"] += _tm.write_units(units, out_dir, base, args.max_units, args.max_bytes)
            elif g.kind == "terms":
                all_concepts = [c for p in g.members for c in p.concepts]
                src = _terms.source_language(all_concepts, opts.source_lang)
                stats["repeated_terms"] += _repeats(g, src)
                if len(g.members) > 1 or opts.join:
                    concepts = _terms.merge_concepts([(p.file, p.concepts) for p in g.members], src, opts.join, log)
                    if len(g.members) > 1:
                        for c in concepts:
                            owners = getattr(c, "_files", [])
                            if owners:
                                c.where = f"{os.path.basename(owners[0])} {c.where}"
                else:
                    concepts = all_concepts
                if opts.split_alternatives:
                    _terms.split_alternatives(concepts, src, g.label, log)
                dnt_list = all(p.dnt_list for p in g.members)
                dnt_hint = all(p.dnt_hint for p in g.members) or dnt_list
                tp = plan_terms(concepts, dnt_list, dnt_hint, g.label, log, opts, src)
                _checks.check_terms(concepts, src, g.label, log,
                                    "Glossary" if tp["target"] == "glossary" else "Term base",
                                    opts.split_alternatives, opts.fix_spaces)
                plan.update(becomes={"glossary": "glossary", "termbase": "term base"}[tp["target"]],
                            why_this_output=tp["why"], do_not_translate=tp.get("dnt", 0), source_language=src)
                if tp.get("mixed"):
                    stats["mixed_dnt_lists"] += 1
                if tp["target"] == "glossary":
                    gl_for_check += [(g.label, e) for e in tp["entries"]]
                    plan.update(entries=len(tp["entries"]),
                                files_needed=-(-len(tp["entries"]) // args.max_entries) if tp["entries"] else 0)
                    if not dry and tp["entries"]:
                        result["outputs"] += _terms.write_glossary(tp["entries"], out_dir, base,
                                                                   args.max_entries, args.max_bytes)
                else:
                    tb_for_check += [(g.label, c) for c in concepts]
                    stats["terms_without_status"] += sum(1 for c in concepts for t in c.terms
                                                         if not t.fields.get("status"))
                    rows = _terms.tb_rows(tp["concepts"], tp["dnt_flags"], g.label, log, opts.term_status)
                    plan.update(concepts=len(rows), terms=sum(len(r) for _, r in rows),
                                files_needed=-(-len(rows) // args.max_concepts) if rows else 0)
                    if not dry and rows:
                        result["outputs"] += _terms.write_term_base(rows, out_dir, base, log, g.label,
                                                                    args.max_concepts, args.max_bytes)
            else:
                entries = _terms.prepare_entries([e for p in g.members for e in p.entries], g.label, log,
                                                 _tm.Resolver(opts.lang_map))
                gl_for_check += [(g.label, e) for e in entries]
                plan.update(becomes="glossary", why_this_output="The file is a glossary", entries=len(entries),
                            do_not_translate=sum(1 for e in entries if e.translatable is False),
                            files_needed=-(-len(entries) // args.max_entries) if entries else 0)
                if not dry and entries:
                    result["outputs"] += _terms.write_glossary(entries, out_dir, base, args.max_entries,
                                                               args.max_bytes)
            result["plan"].append(plan)
            if len(g.members) == 1:
                # One input, one output: the input's own line says what it becomes.
                by_file[g.members[0].file].update({k: v for k, v in plan.items() if k not in ("output", "from")})
            else:
                for p in g.members:
                    by_file[p.file]["merged_into"] = g.name
        _checks.check_tb_vs_glossary(tb_for_check, gl_for_check, log)

        stats["tm_conflicts"] = len({(c["file"], c["language"], c["source"]) for c in log.conflicts})
        stats["special_spaces"] = sum(1 for i in log.issues if i["check"] == "Special spaces in a term")
        stats["alternatives"] = sum(1 for i in log.issues if i["check"] == "Several alternatives in one term")
        decisions = _decisions(parsed, opts, stats)
        result["decisions"] = [d for d in decisions if not d["answered"]]
        result["choices"] = [{"question": d["question"], "using": d["using"]} for d in decisions]
        result["issues"] = _issue_summary(log)
        result["excluded"] = len(log.excluded)
        result["changed"] = len(log.changed)
        result["reasons"] = _reason_counts(log)
        result["not_imported_fields"] = [
            {"file": f, "field": k, "count": v[0], "example": v[1]} for (f, k), v in log.not_imported.items()]
        if needs:
            result["status"] = "needs_input"
            result["needs_input"] = needs
        if not dry and (result["outputs"] or log.excluded or log.changed or log.issues):
            stem = (safe_base(args.name) if args.name else
                    safe_base(files[0][1]) if len(files) == 1 else "")
            report = claim(os.path.join(out_dir, (stem + " - " if stem else "") + "conversion report.xlsx"))
            write_report(report, result, log, decisions)
            result["report"] = report
        if dry:
            result["excluded_examples"] = [dict(zip(["file", "where", "kind", "language", "text", "translation",
                                                     "reason"], r)) for r in log.excluded[:10]]
        return (2 if needs else 0), result
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _repeats(g: Group, src: str) -> int:
    """Source terms that more than one concept of the same file holds (same definition or none)."""
    n = 0
    for p in g.members:
        keys = Counter(k for k in (_terms.concept_key(c, src) for c in p.concepts) if k)
        n += sum(1 for v in keys.values() if v > 1)
    return n


# ---------------------------------------------------------------- questions


def _opt(label: str, description: str, args: list[str], recommended: bool = False) -> dict:
    return {"label": label + (" (recommended)" if recommended else ""), "description": description,
            "args": args, "recommended": recommended}


def _decisions(parsed: list[_readers.Parsed], opts: Options, stats: Counter) -> list[dict]:
    """The choices this conversion depends on. Each has the options to offer, the one used
    when nobody answers, and whether the user has answered it (an option on the command line)."""
    out = []

    def add(key: str, question: str, facts: str, options: list[dict], using: str) -> None:
        out.append({"id": key, "question": question, "facts": facts, "options": options,
                    "answered": opts.answered[key], "using": using})

    def per_language(kind: str) -> list[_readers.Parsed]:
        files = [p for p in parsed if p.kind == kind]
        srcs = Counter()
        for p in files:
            langs = _langs_of(p)
            if langs:
                srcs[langs[0]] += 1
        return files if len(files) > 1 and srcs and srcs.most_common(1)[0][1] > 1 else []

    tb_files = per_language("terms")
    if tb_files:
        n_dnt = sum(1 for p in tb_files if p.dnt_list)
        shared, total = _overlap(tb_files)
        same_list = total and shared >= 0.8 * total
        facts = (f"{len(tb_files)} terminology files share a source language; {shared} of their {total} source "
                 f"terms are in more than one file"
                 + (f". {n_dnt} of the files are do-not-translate lists, which stay a separate glossary" if n_dnt else ""))
        add("merge_terms", "Combine the terminology files into one multilingual term base (and one glossary)?",
            facts, [
                _opt("Combine", "One concept per source term and definition, holding every language "
                     "(e.g. en + de + fr + zh). Best when the files are the same list in different languages.",
                     ["--merge-terms", "yes"], bool(same_list)),
                _opt("Keep separate", "One term base or glossary per file, each with its own two languages. "
                     "Best when each file is its own list.", ["--merge-terms", "no"], not same_list)],
            "combined" if opts.merge_terms else "one per file")
    tm_files = per_language("tm")
    if tm_files:
        add("merge_tm", "Combine the translation memories into one import file?",
            f"{len(tm_files)} memories share a source language", [
                _opt("Keep separate", "One import file per memory: import each into its own memory, or all into "
                     "one, as you like.", ["--merge-tm", "no"], True),
                _opt("Combine", "One file holding every language pair.", ["--merge-tm", "yes"])],
            "combined" if opts.merge_tm else "one per file")
    if stats["mixed_dnt_lists"] or (not opts.answered["dnt_lists"] and any(p.dnt_list for p in parsed)):
        add("dnt_lists", "Do-not-translate lists: import them as a glossary or as a term base?",
            "A file named as a do-not-translate list" + (
                " has a few entries that ARE translated" if stats["mixed_dnt_lists"] else ""), [
                _opt("Glossary", "Entries that keep their source text get Translatable = no, which Vitra "
                     "enforces in translation; the few translated ones stay translatable with their translations.",
                     ["--dnt-lists", "glossary"], True),
                _opt("Term base", "Everything as term base concepts; do-not-translate is only a note, not enforced.",
                     ["--dnt-lists", "termbase"])],
            opts.dnt_lists)
    if stats["repeated_terms"]:
        add("join_duplicates", "Merge rows that repeat the same source term into one concept?",
            f"{stats['repeated_terms']} source terms appear in more than one row of the same file "
            "(same definition, or none)", [
                _opt("Merge", "One concept holding every translation given for that term.",
                     ["--join-duplicates", "yes"], True),
                _opt("Keep separate", "One concept per row, as in the file.", ["--join-duplicates", "no"])],
            "merge" if opts.join else "keep separate")
    if stats["tm_conflicts"]:
        add("conflicts", "A source with several translations: which one should Vitra keep?",
            f"{stats['tm_conflicts']} source segments have 2 or more different translations; Vitra keeps one "
            "per source and language. The report lists every alternative and the one kept", [
                _opt("Most used", _tm.CONFLICT_RULES["frequent"], ["--conflicts", "frequent"], True),
                _opt("Most recent", _tm.CONFLICT_RULES["latest"], ["--conflicts", "latest"]),
                _opt("Last in file", _tm.CONFLICT_RULES["last"], ["--conflicts", "last"])],
            opts.rule)
    if stats["tm_rows_without_status"]:
        add("status", "Which status should the memory's translations get?",
            f"{stats['tm_rows_without_status']} translations have no status in the file", [
                _opt("Approved", "The client's final, reviewed memory.", ["--status", "approved"], True),
                _opt("Verified", "Reviewed once.", ["--status", "verified"]),
                _opt("Unverified", "Not reviewed.", ["--status", "unverified"]),
                _opt("Choose at import", "Left blank: the import dialog's status applies.", ["--status", "none"])],
            opts.status or "blank (set in the import dialog)")
    if stats["terms_without_status"]:
        add("term_status", "Which status should the term base's terms get?",
            f"{stats['terms_without_status']} terms have no status in the file", [
                _opt("Approved", "The client's approved terminology.", ["--term-status", "approved"], True),
                _opt("New", "Proposed terms, to be reviewed in Vitra.", ["--term-status", "new"]),
                _opt("Leave blank", "Vitra's default status for new terms.", ["--term-status", "none"])],
            opts.term_status or "blank (Vitra's default)")
    if stats["inline_tags"]:
        add("tags", "Keep the formatting tags (bold, links, placeholders) in the memory?",
            f"{stats['inline_tags']} inline tags in the memories", [
                _opt("Keep", "Written as <1>…</1> and <2/>, numbered alike in source and translation, so "
                     "segments that differ only by tags stay apart.", ["--tags", "keep"], True),
                _opt("Drop", "Tag code removed, text kept (what a direct TMX upload does). Segments that differ "
                     "only by tags merge into one.", ["--tags", "drop"])],
            "keep" if opts.keep_tags else "drop")
    if stats["special_spaces"]:
        add("fix_spaces", "Replace special spaces (no-break, narrow, tab) in terms with normal spaces?",
            f"{stats['special_spaces']} terms contain them; a term only matches text that has the same spaces", [
                _opt("Leave as is", "Import the terms exactly as the client wrote them.", ["--fix-spaces", "no"],
                     True),
                _opt("Replace", "Normal spaces in the imported terms; every change is in the report.",
                     ["--fix-spaces", "yes"])],
            "replace" if opts.fix_spaces else "leave as is")
    if stats["alternatives"]:
        add("split_alternatives", "Split translations that hold several alternatives (\"a/b\", \"a；b\") "
            "into separate terms?",
            f"{stats['alternatives']} translations look like 2 or more alternatives in one cell", [
                _opt("Leave as is", "One term, exactly as written. Listed in the report for the client.",
                     ["--split-alternatives", "no"], True),
                _opt("Split", "One term per alternative in the same concept.", ["--split-alternatives", "yes"])],
            "split" if opts.split_alternatives else "leave as is")
    return out


def _overlap(files: list[_readers.Parsed]) -> tuple[int, int]:
    """(source terms in 2+ files, all source terms) across terminology files."""
    seen: Counter = Counter()
    for p in files:
        src = _terms.source_language(p.concepts, None)
        seen.update({fold_key(t.text) for c in p.concepts for t in c.terms if t.lang == src})
    return sum(1 for v in seen.values() if v > 1), len(seen)


def _langs_of(p: _readers.Parsed) -> list[str]:
    """[source language, targets…] as written, for grouping per-language files."""
    if p.kind == "tm" and p.tm_rows:
        return [p.tm_rows[0].src_lang.lower()] + sorted({r.tgt_lang.lower() for r in p.tm_rows[:200]})
    if p.kind == "terms" and p.concepts and p.concepts[0].terms:
        return [_terms.source_language(p.concepts, None)]
    if p.kind == "glossary" and p.entries:
        return [p.entries[0].lang.lower()]
    return []


def _issue_summary(log: Log) -> dict:
    by: dict[tuple[str, str, str], list[dict]] = {}
    for i in log.issues:
        by.setdefault((i["level"], i["asset"], i["check"]), []).append(i)
    checks = [{"check": c, "asset": a, "level": lv, "count": len(items),
               "in_vitra": items[0]["in_vitra"],
               "examples": [f"{x['item']} ({x['detail']})" for x in items[:3]]}
              for (lv, a, c), items in by.items()]
    checks.sort(key=lambda x: (x["level"] != "check", -x["count"]))
    return {"total": len(log.issues), "to_check": sum(1 for i in log.issues if i["level"] == "check"),
            "by_check": checks}


def _reason_counts(log: Log) -> dict:
    counts: dict[str, int] = {}
    for r in log.excluded:
        reason = re.sub(r"\s*\(.*|: .*", "", r[6], flags=re.S).strip()
        counts[reason] = counts.get(reason, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: -kv[1]))


# ------------------------------------------------------------------- report


def write_report(path: str, result: dict, log: Log, decisions: list[dict]) -> None:
    summary = []
    for i in result["inputs"]:
        becomes = i.get("becomes") or (f"part of {i['merged_into']}" if i.get("merged_into") else "")
        count = next((i[k] for k in ("units", "concepts", "entries", "rows_read", "concepts_read", "entries_read")
                      if k in i), "")
        summary.append([i["file"], i.get("status", ""), i.get("format", ""), i.get("tool", ""),
                        i.get("content", ""), becomes, i.get("why_this_output", i.get("why", "")), str(count),
                        ", ".join(f"{k} → {v}" for k, v in (i.get("languages") or {}).items()),
                        i.get("reason", "")])
    outputs = [[os.path.basename(o["file"]), o["import_into"],
                str(o.get("units", o.get("concepts", o.get("entries", "")))), str(o.get("rows", "")),
                ", ".join(o.get("source_languages", []) + o.get("target_languages", []) or o.get("languages", [])),
                f"{o['bytes'] / 1024 / 1024:.1f} MB"] for o in result["outputs"]]
    choices = [[d["question"], d["using"], "you chose" if d["answered"] else "default (not asked)",
                d["facts"]] for d in decisions]
    issues = sorted(log.issues, key=lambda i: (i["level"] != "check", i["asset"], i["check"]))
    issue_rows = [Styled([str(n), "Check" if i["level"] == "check" else "Info", i["asset"], i["check"],
                          i["file"], i["where"], i["item"], i["detail"], i["in_vitra"], ""],
                         "amber" if i["level"] == "check" else None) for n, i in enumerate(issues, 1)]
    conflicts = [Styled([c["file"], c["language"], c["source"], c["target"], c["where"], str(c["times"]),
                         c["changed"], "Yes" if c["kept"] else "No", c["why"], ""],
                        "green" if c["kept"] else "red") for c in log.conflicts]
    dups = [[d["file"], d["language"], d["where"], d["source"], d["target"], d["in_vitra"]] for d in log.duplicates]
    reasons = [[k, str(v)] for k, v in _reason_counts(log).items()]
    fields = [[f, k, str(v[0]), v[1]] for (f, k), v in log.not_imported.items()]
    cap = 500_000
    write_xlsx(path, [
        ("Summary", ["Input", "Status", "Format", "Tool", "Content", "Becomes", "Why", "Units / concepts / entries",
                     "Languages (as written → Vitra code)", "Problem"], summary),
        ("Output files", ["File", "Import into", "Units / concepts / entries", "Rows", "Languages", "Size"], outputs),
        ("Choices", ["Question", "Used", "How", "Why it was asked"], choices),
        ("Issues", ["#", "Level", "Asset", "Check", "Input", "Where", "Item", "What was found", "What Vitra will have",
                    "Client comments"], issue_rows[:cap]),
        ("TM conflicts", ["Input", "Language", "Source text", "Translation", "Where", "Times in the file",
                          "Last changed", "Imported", "Why", "Client comments"], conflicts[:cap]),
        ("TM duplicates", ["Input", "Language", "Where", "Source text (special spaces shown)",
                           "Translation (special spaces shown)", "In Vitra"], dups[:cap]),
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
    ap.add_argument("--merge", action="store_true", help="same as --merge-tm yes --merge-terms yes")
    ap.add_argument("--merge-tm", choices=["yes", "no"], help="one memory file from all memories")
    ap.add_argument("--merge-terms", choices=["yes", "no"],
                    help="per-language term lists -> one multilingual term base (and one glossary)")
    ap.add_argument("--join-duplicates", choices=["yes", "no"],
                    help="rows repeating a source term (same or no definition) -> one concept")
    ap.add_argument("--dnt-lists", choices=["glossary", "termbase"],
                    help="what a file named as a do-not-translate list becomes (default glossary)")
    ap.add_argument("--as", dest="as_kind", choices=["tm", "termbase", "term-base", "terms", "glossary"],
                    help="force the output for terminology files")
    ap.add_argument("--dnt", action="store_true", help="treat every term as do-not-translate")
    ap.add_argument("--conflicts", choices=sorted(_tm.CONFLICT_RULES),
                    help="which translation a source with several keeps (default frequent)")
    ap.add_argument("--status", choices=["unverified", "verified", "approved", "none"],
                    help="TM status for translations whose file gives none")
    ap.add_argument("--term-status", choices=["approved", "new", "none"],
                    help="term base status for terms whose file gives none")
    ap.add_argument("--tags", choices=["keep", "drop"], help="inline tags in memories (default keep)")
    ap.add_argument("--fix-spaces", choices=["yes", "no"], help="special spaces in terms -> normal spaces")
    ap.add_argument("--split-alternatives", choices=["yes", "no"],
                    help="a translation holding \"a/b\" alternatives -> one term per alternative")
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
