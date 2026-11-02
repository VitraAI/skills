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
  - a summary
  - the output files
  - every row left out, with its reason
  - every change
  - value mappings
  - fields that are not imported

Nothing is uploaded and no sign-in is needed. You import the files in the Vitra
app, or with the translation-memory and terminology skills.

| Input | Output |
|---|---|
| TMX, XLIFF (incl. sdlxliff, mqxliff, mxliff), SDLTM, PO | Translation memory sheet |
| TBX, MultiTerm XML, termbase spreadsheets | Term base sheet; a glossary when every entry is do-not-translate |
| Glossary sheets, DNT lists | Glossary sheet |

## Requirements

Python 3.10+, standard library only. No network access.
