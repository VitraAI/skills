# Formats and column maps

## What Vitra imports (the output)

Every output file is an .xlsx with one sheet.

**Translation memory**: one row per translation.

| Source language | Source text | Target language | Target text | Status |
|---|---|---|---|---|
| en-US | Save | de-DE | Speichern | approved |

Status is `unverified`, `verified`, `approved` or blank. A blank status takes
the one chosen in the import dialog.

**Term base**: one row per term. The concept columns are filled on the first
row of each concept.

`Concept ID | Domain | Subdomains | URL | Definition | Concept note | Language | Term | Status | Forbidden | Preferred | Case sensitive | Exact match | Note | Usage | Short form | Term type | Part of speech | Gender | Number`

Some columns take fixed values:

| Column | Values |
|---|---|
| Status | new, approved, rejected |
| Term type | full_form, short_form, acronym, abbreviation, phrase, variant, other |
| Part of speech | noun, verb, adjective, adverb, other |
| Gender | masculine, feminine, neuter, other |
| Number | singular, plural, uncountable, other |
| Forbidden, Preferred, Case sensitive, Exact match | yes / no |

**Glossary**: one row per entry, and a column per translation language.

`Term | Language | Description | Translatable | Case sensitive | Tags | <code> | <code> note | …`

`Translatable = no` marks a do-not-translate entry. Vitra rejects any other
column, so extra information goes in Description or in `<code> note`.

## Column maps (`--map`)

Use a column map when `inspect` cannot read a spreadsheet's layout, or reads it
wrongly. The map is a JSON file. Header names are matched case-insensitively.

```json
{
  "kind": "tm",
  "sheet": "Export",
  "header_row": 2,
  "columns": {
    "English":      "text:en-US",
    "Deutsch":      "text:de-DE",
    "DE status":    "status:de-DE",
    "Key":          "ignore",
    "Last edited":  "drop"
  }
}
```

The top-level fields:

- **`kind`**: `tm`, `termbase` or `glossary`.
- **`sheet`**: the sheet's name or its 1-based number. Leave it out to read
  every sheet.
- **`header_row`**: the 1-based row that holds the headers. The default is 1.

Each column takes one role:

| Role | Meaning |
|---|---|
| `source text`, `target text` | A pair layout; the languages come from `source language` / `target language` columns or `--source-lang` / `--target-lang` |
| `source language`, `target language` | The column holds the language of each row |
| `text:<code>` | Text or term in that language (one column per language) |
| `<field>:<code>` | A term field for that language, e.g. `note:fr-FR`, `part of speech:de-DE`, `status:ja-JP`, `synonyms:es-ES` |
| `<field>` | A field for the whole row or concept: `concept id`, `language`, `term`, `domain`, `subdomains`, `definition`, `concept note`, `url`, `dnt`, `translatable`, `tags`, or any term field |
| `extra` | Keep the value as labelled text in the note or description |
| `drop` | Count the column in the report, but don't import it |
| `ignore` | Skip the column silently |

The term fields are: `status`, `forbidden`, `preferred`, `case sensitive`,
`exact match`, `note`, `usage`, `short form`, `term type`, `part of speech`,
`gender`, `number`.

## How layouts are recognized

The header row is the row among the first 15 with the most known column names.
Languages are recognized in three forms:

- codes: `en-US`, `EN_us`, `deu`
- tool names: `German (Germany)`, `Chinese (Simplified, China)`,
  `Norwegian (Bokmal, Norway)`
- inside headers: `Term (fr-FR)`, `German - Part of speech`, `de-DE note`

A row of language names above a row of field names, as in MultiTerm and many
Excel termbase exports, is read as one header. In a sheet with a concept ID
column, a row with no ID continues the concept above it, which is how synonyms
are usually exported.

How the kind of file is decided:

| The sheet has | It is read as |
|---|---|
| Source and target text columns | translation memory |
| Term + Language + a column per language | glossary |
| Language + Term per row | terminology, one term per row |
| A column per language and terminology fields (definition, part of speech, forbidden, DNT…), or a file or sheet name that says glossary, term or DNT | terminology |
| A column per language and nothing else | decided by text length: sentences make a memory, short entries make terminology (`certain: false`) |
| One column | a term list; a do-not-translate list if its header or file name says so |

When the file name holds both languages (`Client_en-US_fr-CA.csv`), a pair layout
takes them from there.
