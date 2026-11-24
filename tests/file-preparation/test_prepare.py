"""file-preparation: every input format -> the sheets VitraTM imports.

Fixtures are written into a temp folder per test, converted with
scripts/prepare.py, and the output workbooks read back with the skill's own
reader. No network, standard library only.
"""

from __future__ import annotations

import contextlib
import io
import json
import os
import sqlite3
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "file-preparation" / "scripts"))

import prepare  # noqa: E402
from _xlsx import XlsxReader, write_xlsx  # noqa: E402


def run(*argv: str) -> tuple[int, dict]:
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        code = prepare.main(list(argv))
    return code, json.loads(buf.getvalue())


def sheet(path: str, n: int | str = 0) -> list[list[str]]:
    rd = XlsxReader(path)
    try:
        return list(rd.rows(n))
    finally:
        rd.close()


def as_dicts(rows: list[list[str]]) -> list[dict]:
    head = rows[0]
    return [{h: (r[i] if i < len(r) else "") for i, h in enumerate(head)} for r in rows[1:]]


class Base(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.out = self.dir / "out"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def write(self, name: str, text: str, encoding: str = "utf-8") -> str:
        p = self.dir / name
        p.write_bytes(text.encode(encoding))
        return str(p)

    def convert(self, *args: str) -> dict:
        code, res = run("convert", *args, "--out", str(self.out))
        self.assertEqual(code, 0, res)
        return res

    def outputs(self, label: str) -> list[str]:
        return sorted(str(p) for p in self.out.glob(f"*{label}*.xlsx"))


TMX = """<?xml version="1.0" encoding="UTF-16"?>
<tmx version="1.4"><header srclang="EN-US" creationtool="SDL Language Platform" segtype="sentence"
 o-tmf="x" adminlang="en" datatype="xml"/><body>
<tu tuid="1" changedate="20240101T000000Z"><prop type="x-Client">Acme</prop>
 <tuv xml:lang="en-US"><seg>Click <bpt i="1">&lt;b&gt;</bpt>Save<ept i="1">&lt;/b&gt;</ept> now</seg></tuv>
 <tuv xml:lang="de-DE"><seg>Klicken Sie jetzt auf <bpt i="1">&lt;b&gt;</bpt>Speichern<ept i="1">&lt;/b&gt;</ept></seg></tuv>
 <tuv xml:lang="fr-FR"><seg>Cliquez sur Enregistrer</seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Hello</seg></tuv><tuv xml:lang="de-DE"><seg>Hallo</seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Hello</seg></tuv><tuv xml:lang="de-DE"><seg>Servus</seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Hello</seg></tuv><tuv xml:lang="de-DE"><seg>Hallo</seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Empty</seg></tuv><tuv xml:lang="de-DE"><seg></seg></tuv></tu>
<tu><tuv xml:lang="en-US"><seg>Odd</seg></tuv><tuv xml:lang="xx-QQ"><seg>Zzz</seg></tuv></tu>
</body></tmx>"""


class TmFormats(Base):
    def test_tmx_utf16_tags_conflicts_and_languages(self) -> None:
        res = self.convert(self.write("acme.tmx", TMX, "utf-16"))
        rows = as_dicts(sheet(self.outputs("TM")[0]))
        # Inline tags kept as Vitra numbers them, the target's matched to the source's.
        self.assertEqual(rows[0]["Source text"], "Click <1>Save</1> now")
        self.assertEqual(rows[0]["Target text"], "Klicken Sie jetzt auf <1>Speichern</1>")
        hello = [r for r in rows if r["Source text"] == "Hello"]
        self.assertEqual([r["Target text"] for r in hello], ["Hallo"])  # most frequent wins
        self.assertNotIn("Odd", [r["Source text"] for r in rows])
        self.assertEqual(res["excluded"], 3)  # Servus, empty target, unknown language
        report = sheet(res["report"], "Left out")
        reasons = " ".join(r[6] for r in report[1:])
        self.assertIn("not in Vitra's language list", reasons)
        self.assertIn("Another translation of the same source was kept", reasons)
        self.assertEqual(res["inputs"][0]["languages"]["de-DE"], "de-DE")

    def test_split_by_units_keeps_every_unit_whole(self) -> None:
        body = "".join(
            f'<tu><tuv xml:lang="en"><seg>s{i}</seg></tuv><tuv xml:lang="de"><seg>d{i}</seg></tuv>'
            f'<tuv xml:lang="fr"><seg>f{i}</seg></tuv></tu>' for i in range(25))
        p = self.write("big.tmx", f'<tmx version="1.4"><header srclang="en"/><body>{body}</body></tmx>')
        res = self.convert(p, "--max-units", "10")
        files = self.outputs("TM - part")
        self.assertEqual(len(files), 3)
        self.assertEqual([o["units"] for o in res["outputs"]], [10, 10, 5])
        for f in files:
            rows = as_dicts(sheet(f))
            per = {}
            for r in rows:
                per.setdefault(r["Source text"], set()).add(r["Target language"])
            self.assertTrue(all(v == {"de", "fr"} for v in per.values()))

    def test_sdlxliff_segments_and_status(self) -> None:
        x = """<?xml version="1.0" encoding="utf-8"?>
<xliff version="1.2" xmlns="urn:oasis:names:tc:xliff:document:1.2" xmlns:sdl="http://sdl.com/FileTypes/SdlXliff/1.0">
<file source-language="en-US" target-language="ja-JP"><body>
<trans-unit id="u1"><source>One. Two.</source>
<seg-source><mrk mtype="seg" mid="1">One.</mrk> <mrk mtype="seg" mid="2">Two.</mrk></seg-source>
<target><mrk mtype="seg" mid="1">一。</mrk> <mrk mtype="seg" mid="2"></mrk></target>
<sdl:seg-defs><sdl:seg id="1" conf="ApprovedSignOff"/><sdl:seg id="2" conf="Draft"/></sdl:seg-defs>
</trans-unit></body></file></xliff>"""
        self.convert(self.write("doc.sdlxliff", x))
        rows = as_dicts(sheet(self.outputs("TM")[0]))
        self.assertEqual(rows, [{"Source language": "en-US", "Source text": "One.", "Target language": "ja-JP",
                                 "Target text": "一。", "Status": "approved"}])

    def test_xliff2(self) -> None:
        x = """<xliff xmlns="urn:oasis:names:tc:xliff:document:2.0" version="2.0" srcLang="en" trgLang="it">
<file id="f"><unit id="1"><segment state="reviewed"><source>Hi <ph id="1"/>there</source>
<target>Ciao <ph id="1"/>a tutti</target></segment></unit></file></xliff>"""
        self.convert(self.write("a.xlf", x))
        r = as_dicts(sheet(self.outputs("TM")[0]))[0]
        self.assertEqual((r["Source text"], r["Target text"], r["Status"]),
                         ("Hi <1/>there", "Ciao <1/>a tutti", "verified"))

    def test_sdltm(self) -> None:
        p = str(self.dir / "mem.sdltm")
        con = sqlite3.connect(p)
        con.execute("CREATE TABLE translation_memories (id INT, source_language TEXT, target_language TEXT)")
        con.execute("INSERT INTO translation_memories VALUES (1, 'en-GB', 'es-ES')")
        con.execute("CREATE TABLE translation_units (id INT, source_segment TEXT, target_segment TEXT, "
                    "creation_date TEXT, change_date TEXT)")
        seg = ('<Segment><Elements><Text><Value>{}</Value></Text><Tag><Type>Standalone</Type></Tag>'
               '<Text><Value>{}</Value></Text></Elements><CultureName>{}</CultureName></Segment>')
        con.execute("INSERT INTO translation_units VALUES (1, ?, ?, '2020-01-01', '2021-01-01')",
                    (seg.format("Press ", " to start", "en-GB"), seg.format("Pulse ", " para empezar", "es-ES")))
        con.commit()
        con.close()
        self.convert(p)
        r = as_dicts(sheet(self.outputs("TM")[0]))[0]
        self.assertEqual((r["Source text"], r["Target text"], r["Target language"]),
                         ("Press <1/> to start", "Pulse <1/> para empezar", "es-ES"))

    def test_po_needs_source_language_then_converts(self) -> None:
        po = ('msgid ""\nmsgstr ""\n"Language: pt_BR\\n"\n\n#: a.c:1\nmsgid "Open"\nmsgstr "Abrir"\n\n'
              '#, fuzzy\nmsgid "Close"\nmsgstr "Fechar"\n\nmsgid "One file"\nmsgid_plural "%d files"\n'
              'msgstr[0] "Um arquivo"\nmsgstr[1] "%d arquivos"\n')
        p = self.write("app.po", po)
        code, res = run("convert", p, "--out", str(self.out))
        self.assertEqual(code, 2)
        self.assertEqual(res["needs_input"][0]["option"], "--source-lang")
        self.convert(p, "--source-lang", "en-US")
        rows = as_dicts(sheet(self.outputs("TM")[0]))
        self.assertEqual([r["Source text"] for r in rows], ["Open", "One file", "%d files"])
        self.assertEqual(rows[0]["Target language"], "pt-BR")

    def test_csv_pair_languages_from_filename(self) -> None:
        p = self.write("export_en-US_fr-CA.csv", "Source;Target;Created by\nGood morning everyone;Bonjour à tous;bob\n")
        self.convert(p)
        r = as_dicts(sheet(self.outputs("TM")[0]))[0]
        self.assertEqual((r["Source language"], r["Target language"]), ("en-US", "fr-CA"))

    def test_wide_sheet_of_sentences_is_a_memory(self) -> None:
        p = str(self.dir / "strings.xlsx")
        write_xlsx(p, [("S", ["en-US", "de-DE", "es-ES"], [
            ["Your order has been shipped and will arrive soon", "Ihre Bestellung wurde versandt", ""],
            ["Please sign in again to continue with checkout", "Bitte melden Sie sich erneut an", "Inicia sesión"],
            ["We could not process your payment at this time", "Zahlung fehlgeschlagen", "Pago fallido"]])])
        res = self.convert(p)
        self.assertEqual(res["inputs"][0]["becomes"], "translation memory")
        self.assertEqual(res["outputs"][0]["rows"], 5)


TBX = """<?xml version="1.0"?><martif type="TBX"><text><body>
<termEntry id="c7"><descrip type="subjectField">Software</descrip><descrip type="definition">To store data.</descrip>
<admin type="createdBy">jo</admin>
<langSet xml:lang="en-US"><tig><term>save</term><termNote type="partOfSpeech">verb</termNote>
<termNote type="administrativeStatus">preferredTerm-admn-sts</termNote></tig>
<tig><term>store</term><termNote type="administrativeStatus">deprecatedTerm-admn-sts</termNote></tig></langSet>
<langSet xml:lang="de-DE"><tig><term>speichern</term><termNote type="grammaticalGender">n</termNote>
<descrip type="context">Datei speichern</descrip></tig></langSet>
</termEntry>
<termEntry id="c8"><langSet xml:lang="en-US"><tig><term>&amp;amp;Cancel</term></tig></langSet>
<langSet xml:lang="de-DE"><tig><term>Abbrechen</term><termNote type="partOfSpeech">interjection</termNote></tig></langSet></termEntry>
</body></text></martif>"""

MULTITERM = """<?xml version="1.0" encoding="UTF-16"?><mtf>
<conceptGrp><concept>1</concept><transacGrp><transac type="origination">x</transac></transacGrp>
<languageGrp><language type="English" lang="EN"/><termGrp><term>Acme Cloud</term></termGrp></languageGrp>
<languageGrp><language type="German" lang="DE"/><termGrp><term>Acme Cloud</term></termGrp></languageGrp>
</conceptGrp>
<conceptGrp><concept>2</concept>
<languageGrp><language type="English" lang="EN"/><termGrp><term>Acme Drive</term>
<descripGrp><descrip type="Do Not Translate">Yes</descrip></descripGrp></termGrp></languageGrp>
</conceptGrp></mtf>"""


class Terminology(Base):
    def test_tbx_to_term_base_with_fields(self) -> None:
        res = self.convert(self.write("terms.tbx", TBX))
        self.assertEqual(res["inputs"][0]["becomes"], "term base")
        rows = as_dicts(sheet(self.outputs("Term base")[0]))
        save = next(r for r in rows if r["Term"] == "save")
        self.assertEqual((save["Concept ID"], save["Domain"], save["Definition"], save["Preferred"],
                          save["Part of speech"]), ("c7", "Software", "To store data.", "yes", "verb"))
        store = next(r for r in rows if r["Term"] == "store")
        self.assertEqual(store["Forbidden"], "yes")
        de = next(r for r in rows if r["Term"] == "speichern")
        self.assertEqual((de["Gender"], de["Usage"]), ("neuter", "Datei speichern"))
        cancel = next(r for r in rows if r["Language"] == "en-US" and "Cancel" in r["Term"])
        self.assertEqual(cancel["Term"], "&Cancel")  # double-escaped entity decoded once by XML, once here
        self.assertIn("Original spelling", cancel["Note"])
        ab = next(r for r in rows if r["Term"] == "Abbrechen")
        self.assertEqual((ab["Part of speech"], ab["Note"]), ("", "Part of speech: interjection"))

    def test_dnt_only_multiterm_becomes_glossary(self) -> None:
        res = self.convert(self.write("brands.xml", MULTITERM, "utf-16"))
        self.assertEqual(res["inputs"][0]["becomes"], "glossary")
        rows = as_dicts(sheet(self.outputs("Glossary")[0]))
        self.assertEqual([(r["Term"], r["Language"], r["Translatable"]) for r in rows],
                         [("Acme Cloud", "en", "no"), ("Acme Drive", "en", "no")])
        self.assertEqual(list(rows[0].keys()), ["Term", "Language", "Description", "Translatable",
                                                "Case sensitive", "Tags"])

    def test_mixed_dnt_stays_term_base(self) -> None:
        p = self.write("glossary.csv", "en-US,fr-FR,DNT\nAcme,Acme,yes\ncart,panier,\n")
        res = self.convert(p)
        self.assertEqual(res["inputs"][0]["becomes"], "term base")
        self.assertEqual(res["inputs"][0]["do_not_translate"], 1)
        rows = as_dicts(sheet(self.outputs("Term base")[0]))
        self.assertIn("Do not translate.", rows[0]["Concept note"])

    def test_single_column_dnt_list(self) -> None:
        p = self.write("DNT list.csv", "Do not translate\nVitra\nUniverse\n")
        code, res = run("convert", p, "--out", str(self.out))
        self.assertEqual(code, 2)
        res = self.convert(p, "--source-lang", "en")
        self.assertEqual(res["inputs"][0]["becomes"], "glossary")
        self.assertEqual(res["outputs"][0]["do_not_translate"], 2)

    def test_native_glossary_merges_duplicates(self) -> None:
        p = self.write("gl.csv", "Term,Language,Description,Translatable,hi-IN,hi-IN note\n"
                                 "Invoice,en,Bill,yes,चालान,\ninvoice,en,,yes,बीजक,\n")
        res = self.convert(p)
        self.assertEqual(res["inputs"][0]["becomes"], "glossary")
        rows = as_dicts(sheet(self.outputs("Glossary")[0]))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["hi-IN"], "चालान")
        self.assertIn("बीजक", rows[0]["hi-IN note"])

    def test_wide_terminology_with_language_fields(self) -> None:
        p = str(self.dir / "Termbase export.xlsx")
        write_xlsx(p, [("Terms", ["Entry ID", "Subject", "English (United States)", "English definition",
                                  "German", "German - Part of speech", "Created by"],
                        [["10", "UI", "Dashboard", "Main screen", "Dashboard\nÜbersicht", "noun", "ann"]])])
        res = self.convert(p)
        rows = as_dicts(sheet(self.outputs("Term base")[0]))
        self.assertEqual([r["Term"] for r in rows], ["Dashboard", "Dashboard", "Übersicht"])
        self.assertEqual(rows[0]["Definition"], "Main screen")
        self.assertEqual(rows[1]["Part of speech"], "noun")
        self.assertEqual(res["not_imported_fields"][0]["field"], 'Column "Created by"')

    def test_term_base_split_keeps_sharing_concepts_together(self) -> None:
        lines = ["Concept ID,Language,Term"]
        for i in range(9):
            lines += [f"{i},en,term{i}", f"{i},de,Begriff{i}"]
        lines += ["99,en,term0", "99,fr,terme0"]  # shares "term0" with concept 0
        res = self.convert(self.write("tb.csv", "\n".join(lines) + "\n"), "--max-concepts", "4")
        self.assertEqual(sum(o["concepts"] for o in res["outputs"]), 10)
        for f in self.outputs("Term base"):
            ids = {r["Concept ID"] for r in as_dicts(sheet(f))}
            if "0" in ids:
                self.assertIn("99", ids)

    def test_as_glossary_folds_synonyms_and_forbidden_into_notes(self) -> None:
        res = self.convert(self.write("terms.tbx", TBX), "--as", "glossary")
        rows = as_dicts(sheet(self.outputs("Glossary")[0]))
        save = next(r for r in rows if r["Term"] == "save")
        self.assertIn("Also: store", save["Description"])
        self.assertEqual(save["de-DE"], "speichern")
        self.assertEqual(res["inputs"][0]["becomes"], "glossary")


class Inputs(Base):
    def test_zip_and_unsupported_files(self) -> None:
        z = self.dir / "client.zip"
        with zipfile.ZipFile(z, "w") as zf:
            zf.writestr("tm/a.tmx", '<tmx version="1.4"><header srclang="en"/><body><tu><tuv xml:lang="en">'
                                    '<seg>A</seg></tuv><tuv xml:lang="de"><seg>B</seg></tuv></tu></body></tmx>')
            zf.writestr("readme.pdf", "%PDF-1.4")
        (self.dir / "old.xls").write_bytes(b"\xd0\xcf\x11\xe0" + b"\0" * 100)
        res = self.convert(str(z), str(self.dir / "old.xls"))
        self.assertEqual(len(res["outputs"]), 1)
        bad = [i for i in res["inputs"] if i.get("status") == "unsupported"]
        self.assertIn("save it as .xlsx", bad[0]["reason"])

    def test_inspect_writes_nothing(self) -> None:
        code, res = run("inspect", self.write("acme.tmx", TMX, "utf-16"))
        self.assertEqual(code, 0)
        self.assertFalse(self.out.exists())
        self.assertEqual(res["inputs"][0]["units"], 2)

    def test_lang_map(self) -> None:
        p = self.write("x.tmx", '<tmx version="1.4"><header srclang="en"/><body><tu><tuv xml:lang="en">'
                                '<seg>A</seg></tuv><tuv xml:lang="xx-QQ"><seg>B</seg></tuv></tu></body></tmx>')
        self.convert(p, "--lang-map", "xx-QQ=fil-PH", "--lang-map", "en=en-US")
        r = as_dicts(sheet(self.outputs("TM")[0]))[0]
        self.assertEqual((r["Source language"], r["Target language"]), ("en-US", "fil-PH"))

    def test_xlsx_writer_keeps_text_exactly(self) -> None:
        p = str(self.dir / "t.xlsx")
        tricky = ["=1+1", "01/02", "a\nb", "_x0041_", "<b>&amp;</b>", " lead"]
        write_xlsx(p, [("S", ["v"], [[t] for t in tricky])])
        self.assertEqual([r[0] for r in sheet(p)[1:]], tricky)


# A per-language term list as Acclaro, XTM and similar tools export it: camelCase headers,
# the language of each row in its own column, "N/A" for an empty cell.
PAIR_HEADER = ["SourceLanguage", "TargetLanguage", "SourceTermDefinition", "TargetTermDefinition",
               "SourcePartOfSpeech", "SourceContext", "ConceptDefinition", "TargetProduct", "TargetUsageNote"]


def pair_list(path: str, target: str, rows: list[tuple]) -> str:
    write_xlsx(path, [("TermEntries", PAIR_HEADER,
                       [["EN-US", target, en, tr, "N/A", ctx, d, "Acme web", note] for en, tr, ctx, d, note in rows])])
    return path


class Interactive(Base):
    def lists(self) -> list[str]:
        """The same term list in German and French, plus German and French do-not-translate lists."""
        de = pair_list(str(self.dir / "Acme_TermList_EN-US_DE-DE.xlsx"), "DE-DE", [
            ("cart", "Warenkorb", "Add to cart", "Where items wait", "N/A"),
            ("checkout", "Kasse", "N/A", "Paying for the cart", "N/A"),
            ("support plan", "Supportplan", "N/A", "A paid plan", "N/A"),
            ("support plan", "Supportvertrag", "N/A", "A contract for help", "N/A")])
        fr = pair_list(str(self.dir / "Acme_TermList_EN-US_FR-FR.xlsx"), "FR-FR", [
            ("cart", "panier", "Add to cart", "Where items wait", "N/A"),
            ("checkout", "N/A", "N/A", "Paying for the cart", "N/A"),
            ("support plan", "forfait d’assistance", "N/A", "A paid plan", "N/A")])
        dnt_de = pair_list(str(self.dir / "Acme_DNT_EN-US_DE-DE.xlsx"), "DE-DE", [
            ("AcmePay", "AcmePay", "N/A", "Payment product", "N/A"),
            ("cart", "cart", "N/A", "N/A", "N/A"),
            ("Acme Cloud", "Acme Cloud 365", "N/A", "N/A", "N/A")])
        dnt_fr = pair_list(str(self.dir / "Acme_DNT_EN-US_FR-FR.xlsx"), "FR-FR", [
            ("AcmePay", "AcmePay", "N/A", "Payment product", "N/A"),
            ("cart", "cart", "N/A", "N/A", "N/A"),
            ("Acme Cloud", "Acme Cloud 365", "N/A", "N/A", "N/A"),
            ("Acme Go", "Acme Go", "N/A", "N/A", "N/A")])
        return [de, fr, dnt_de, dnt_fr]

    def test_pair_term_list_headers_languages_and_placeholders(self) -> None:
        """What it tests: a camelCase pair layout with per-row language columns is read with its
        real header row; "N/A" cells are empty, and an "N/A" term is left out and reported.
        How it verifies it: the term base holds every row's terms with the right fields, and the
        report and inspect list the placeholder."""
        de, fr = self.lists()[:2]
        res = self.convert(fr, "--term-status", "approved")
        self.assertEqual(res["inputs"][0]["column_map"]["header_row"], 1)
        rows = as_dicts(sheet(self.outputs("Term base")[0]))
        cart_en = next(r for r in rows if r["Term"] == "cart")
        self.assertEqual((cart_en["Language"], cart_en["Definition"], cart_en["Domain"], cart_en["Usage"],
                          cart_en["Part of speech"], cart_en["Status"]),
                         ("en-US", "Where items wait", "Acme web", "Add to cart", "", "approved"))
        self.assertNotIn("N/A", [r["Term"] for r in rows])
        checks = {c["check"]: c for c in res["issues"]["by_check"]}
        self.assertEqual(checks["Placeholder instead of a term"]["count"], 1)
        self.assertIn('The cell says "N/A" instead of a term', res["reasons"])

    def test_inspect_asks_the_open_questions_and_stops_asking_once_answered(self) -> None:
        """What it tests: inspect returns the decisions this data needs, recommended option
        first, and a decision given on the command line is no longer asked.
        How it verifies it: the question ids before and after passing the answers."""
        files = self.lists()
        code, res = run("inspect", *files)
        self.assertEqual(code, 0)
        asked = {d["id"]: d for d in res["decisions"]}
        self.assertTrue({"merge_terms", "dnt_lists", "term_status"} <= set(asked))
        merge = asked["merge_terms"]
        self.assertTrue(merge["options"][0]["recommended"])
        self.assertEqual(merge["options"][0]["args"], ["--merge-terms", "yes"])
        code, res = run("inspect", *files, "--merge-terms", "yes", "--dnt-lists", "glossary",
                        "--term-status", "new")
        self.assertEqual({d["id"] for d in res["decisions"]} & {"merge_terms", "dnt_lists", "term_status"}, set())

    def test_merge_per_language_lists_into_one_term_base_and_one_glossary(self) -> None:
        """What it tests: --merge-terms joins per-language lists into multilingual concepts (same
        source term and definition), keeps homographs apart, and turns the do-not-translate lists
        into one glossary where translated entries and one-language entries stay translatable.
        How it verifies it: concepts and glossary rows in the output, and the Issues sheet."""
        res = self.convert(*self.lists(), "--merge-terms", "yes", "--term-status", "approved")
        self.assertEqual(len(self.outputs("Term base")), 1)
        tb = as_dicts(sheet(self.outputs("Term base")[0]))
        concepts: dict[str, set] = {}
        for r in tb:
            concepts.setdefault(r["Concept ID"], set()).add((r["Language"], r["Term"]))
        self.assertIn({("en-US", "cart"), ("de-DE", "Warenkorb"), ("fr-FR", "panier")}, concepts.values())
        self.assertIn({("en-US", "checkout"), ("de-DE", "Kasse")}, concepts.values())  # fr was N/A
        plans = [c for c in concepts.values() if ("en-US", "support plan") in c]
        self.assertEqual(len(plans), 2)  # two meanings stay two concepts
        gl = {r["Term"]: r for r in as_dicts(sheet(self.outputs("Glossary")[0]))}
        self.assertEqual(gl["AcmePay"]["Translatable"], "no")
        self.assertEqual((gl["Acme Cloud"]["Translatable"], gl["Acme Cloud"]["de-DE"]), ("yes", "Acme Cloud 365"))
        self.assertEqual((gl["Acme Go"]["Translatable"], gl["Acme Go"]["fr-FR"], gl["Acme Go"].get("de-DE", "")),
                         ("yes", "Acme Go", ""))
        checks = {c["check"] for c in res["issues"]["by_check"]}
        self.assertTrue({"Translated entry on a do-not-translate list", "Do-not-translate in some languages only",
                         "Glossary and term base disagree", "Same term, different meanings"} <= checks)
        issues = as_dicts(sheet(res["report"], "Issues"))
        clash = next(i for i in issues if i["Check"] == "Glossary and term base disagree")
        self.assertEqual(clash["Item"], "cart")

    def test_join_duplicates_within_one_file(self) -> None:
        """What it tests: rows repeating a source term without a definition become one concept
        only when --join-duplicates yes is given.
        How it verifies it: the number of concepts holding "hit" with and without the option."""
        p = pair_list(str(self.dir / "Music_EN-US_IT-IT.xlsx"), "IT-IT", [
            ("hit", "successo", "N/A", "N/A", "N/A"), ("hit", "hit", "N/A", "N/A", "N/A"),
            ("track", "brano", "N/A", "N/A", "N/A")])
        code, res = run("inspect", p)
        self.assertIn("join_duplicates", {d["id"] for d in res["decisions"]})
        res = self.convert(p, "--join-duplicates", "yes")
        self.assertEqual(res["outputs"][0]["concepts"], 2)
        rows = as_dicts(sheet(self.outputs("Term base")[0]))
        self.assertEqual(sorted(r["Term"] for r in rows if r["Language"] == "it-IT"), ["brano", "hit", "successo"])

    def test_cleanups_are_flagged_and_applied_only_when_chosen(self) -> None:
        """What it tests: special spaces, alternatives in one cell, ending shorthand and broken
        brackets are reported; --fix-spaces and --split-alternatives change only what they name.
        How it verifies it: the terms written with and without the options."""
        p = pair_list(str(self.dir / "UI_EN-US_IT-IT.xlsx"), "IT-IT", [
            ("track", "traccia/brano", "N/A", "N/A", "N/A"),
            ("favorite", "preferito/a", "N/A", "N/A", "N/A"),
            ("tell us", "dicci\u00a0subito", "N/A", "N/A", "N/A"),
            ("WHQL", "WHQL (Windows Hardware Quality Labs", "N/A", "N/A", "N/A")])
        code, res = run("inspect", p)
        checks = {c["check"]: c["count"] for c in res["issues"]["by_check"]}
        self.assertEqual((checks["Several alternatives in one term"], checks["Ending shorthand in a term"],
                          checks["Special spaces in a term"], checks["Unbalanced brackets"]), (1, 1, 1, 1))
        self.assertTrue({"fix_spaces", "split_alternatives"} <= {d["id"] for d in res["decisions"]})
        self.convert(p, "--fix-spaces", "yes", "--split-alternatives", "yes")
        it = sorted(r["Term"] for r in as_dicts(sheet(self.outputs("Term base")[0])) if r["Language"] == "it-IT")
        self.assertEqual(it, ["WHQL (Windows Hardware Quality Labs", "brano", "dicci subito", "preferito/a", "traccia"])


class TmChoices(Base):
    TMX = """<tmx version="1.4"><header srclang="en"/><body>
<tu changedate="20200101T000000Z"><tuv xml:lang="en"><seg>Save</seg></tuv><tuv xml:lang="de"><seg>Sichern</seg></tuv></tu>
<tu changedate="20200101T000000Z"><tuv xml:lang="en"><seg>Save</seg></tuv><tuv xml:lang="de"><seg>Sichern</seg></tuv></tu>
<tu changedate="20250101T000000Z"><tuv xml:lang="en"><seg>Save</seg></tuv><tuv xml:lang="de"><seg>Speichern</seg></tuv></tu>
<tu><tuv xml:lang="en"><seg>Go\u00a0now</seg></tuv><tuv xml:lang="de"><seg>Los</seg></tuv></tu>
<tu><tuv xml:lang="en"><seg>Go now</seg></tuv><tuv xml:lang="de"><seg>Los</seg></tuv></tu>
<tu><tuv xml:lang="en"><seg>Open <ph x="1">{0}</ph> or <bpt i="1" x="2">&lt;b&gt;</bpt>file<ept i="1">&lt;/b&gt;</ept></seg></tuv>
<tuv xml:lang="de"><seg><bpt i="1" x="2">&lt;b&gt;</bpt>Datei<ept i="1">&lt;/b&gt;</ept> oder <ph x="1">{0}</ph> öffnen</seg></tuv></tu>
</body></tmx>"""

    def test_conflict_rule_and_conflict_sheet(self) -> None:
        """What it tests: --conflicts picks the translation kept; the report's TM conflicts sheet
        lists every alternative, kept or not, and duplicates are listed with special spaces shown.
        How it verifies it: the kept text under each rule and the report sheets."""
        p = self.write("ui.tmx", self.TMX)
        code, res = run("inspect", p)
        self.assertIn("conflicts", {d["id"] for d in res["decisions"]})
        res = self.convert(p)
        rows = {r["Source text"]: r["Target text"] for r in as_dicts(sheet(self.outputs("TM")[0]))}
        self.assertEqual(rows["Save"], "Sichern")  # most used
        conflicts = as_dicts(sheet(res["report"], "TM conflicts"))
        self.assertEqual([(c["Translation"], c["Imported"]) for c in conflicts], [("Sichern", "Yes"), ("Speichern", "No")])
        dups = as_dicts(sheet(res["report"], "TM duplicates"))
        self.assertTrue(any("[NBSP]" in d["Source text (special spaces shown)"] for d in dups))
        self.assertEqual(res["reasons"], {"Another translation of the same source was kept": 1})
        self.convert(p, "--conflicts", "latest")
        rows = {r["Source text"]: r["Target text"] for r in as_dicts(sheet(self.outputs("TM")[0]))}
        self.assertEqual(rows["Save"], "Speichern")

    def test_tags_follow_the_source_numbering_or_are_dropped(self) -> None:
        """What it tests: a target that reorders its tags keeps the source's numbers (TMX x),
        and --tags drop removes tag code as a direct TMX upload does.
        How it verifies it: the written source and target text."""
        p = self.write("ui.tmx", self.TMX)
        self.convert(p, "--tags", "keep")
        row = next(r for r in as_dicts(sheet(self.outputs("TM")[0])) if r["Source text"].startswith("Open"))
        self.assertEqual((row["Source text"], row["Target text"]), ("Open <1/> or <2>file</2>", "<2>Datei</2> oder <1/> öffnen"))
        self.convert(p, "--tags", "drop")
        row = next(r for r in as_dicts(sheet(self.outputs("TM")[0])) if r["Source text"].startswith("Open"))
        self.assertEqual(row["Source text"], "Open  or file")


if __name__ == "__main__":
    unittest.main()
