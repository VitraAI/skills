# file-preparation

File Preparation is an agent skill for Vitra Universe. It converts translation
memories, term bases and glossaries from any tool into files Vitra imports.
Each file is split to fit Vitra's per-file limits, and a report lists
everything that was kept, changed or left out.

Drop this folder into your agent's skills directory. The agent reads
`SKILL.md` and does the rest, so you don't run anything by hand.

## How it works

`scripts/prepare.py` reads the files locally and writes:

- one or more import files per input:
  - `<name> - TM.xlsx`
  - `<name> - Term base.xlsx`
  - `<name> - Glossary.xlsx`
  - a large file is written in parts: `… - part 01 of 03.xlsx`
- `conversion report.xlsx`, with these sheets:
  - a summary, and the output files
  - the choices made, and which were the user's answers
  - every problem found in the data (placeholders, broken brackets, alternatives
    in one cell, special spaces, glossary vs term base clashes…), with what Vitra
    will hold and a column for the client's comments
  - every TM source with several translations, colour-coded kept or not
  - every repeated TM unit merged into one
  - every row left out, with its reason
  - every change
  - value mappings
  - fields that are not imported

Before converting, the agent tells you what each file is and what it will
become, lists the problems found, and asks the few choices that matter: one
multilingual term base or one per language, which of several translations to
keep, statuses, inline tags and optional clean-ups. Each comes with a
recommended answer.

Nothing is uploaded and no sign-in is needed. You import the files in the Vitra
app, or with the translation-memory and terminology skills.

| Input | Output |
|---|---|
| TMX, XLIFF (incl. sdlxliff, mqxliff, mxliff), SDLTM, PO | Translation memory sheet |
| TBX, MultiTerm XML, termbase spreadsheets | Term base sheet; a glossary when every entry is do-not-translate |
| Glossary sheets, DNT lists | Glossary sheet |

## Requirements

Python 3.10+, standard library only. No network access.
