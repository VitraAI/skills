---
name: document-translation
description: >-
  Translates documents and text with the Vitra Universe API, keeping the
  original layout and formatting: Word, PowerPoint, Excel, CSV, PDF, HTML,
  JSON, XML, XLIFF and plain text — one file, a batch, or a whole Drive folder
  — into several languages at once, through the organization's translation
  memory; then scores, proofreads or back-translates the result on request.
  Use it whenever the user wants files or text translated or checked —
  "translate this contract into German", "translate everything in our Q3
  folder", "proofread the French version", "back-translate it so I can check". Not for subtitles (subtitle-translation), text in
  images (image-translation) or video (video-dubbing).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API only.
  Needs VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.1"
  display-name: Document Translation
  category: Localization
  tags: Documents, Translation, Popular
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Document Translation

Translates a file or text and saves the translated files, formatting kept.
Each script prints **one line of JSON**; three fields drive the flow:
`status`, `error.ask` (a question for the user) and `next_action`. Scripts
wait for their own jobs: never poll, never re-run to "check".

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: continue without the steps in
`cannot`. `blocked`: stop and tell the user which steps their key can't do;
their Vitra admin can grant them. Key missing (exit 2): relay the setup lines.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The file, or the text | yes | `.docx .pptx .xlsx .csv .pdf .html .json .xml .xliff .txt`, or text in the request |
| Target languages | yes | Ask if not given. Names or codes both work: `French`, `fr-FR` |
| Translation memory | when several fit | See step 1 |

The source language is the memory's. If the document is in another language,
say so before translating.

## The flow

```
- [ ] 1. Translation memory   (⏸ ask if several fit)
- [ ] 2. Translate            (⏸ confirm: spends credits) → translated files
- [ ] 3. Check and polish     (only if the user wants: ⏸ each spends credits)
```

### 1. Translation memory ⏸

```bash
python3 scripts/list_tms.py --target-language French
```

**One fits:** use it and say so. **Several:** ask which, by name; the wrong one
writes the wrong wording into a memory the whole organization reuses.
**None:** the user needs one first: they can create it in Vitra (Translation
Memory), or with the translation-memory skill.

### 2. Translate ⏸

Confirm the files, languages and memory: translation spends credits per word.

| What the user has | Run |
|---|---|
| One file, or text | `translate_document.py --file contract.docx --target-language German [--target-language French]` (or `--text "…"`) |
| Several files of one kind (up to 20) | `translate_batch.py --file a.docx --file b.docx --target-language German` |
| A whole folder in their Vitra Drive | `translate_folder.py --folder "Q3 manuals" --target-language German` → preview; then add `--confirm` |

All take `[--tm-name "<memory>"]`. `translate_document.py` options:
`--out-dir` (default `./translated`), `--columns 1,3` (CSV: only those
columns, 0-based; ask which hold prose if unsure), `--keep-first-row` (Excel:
leave headings as they are).

A folder run **previews first**: show how many files, what's skipped and the
output folder, then run it again with `--confirm` once the user agrees. Its
results land in a new folder in their Drive (`output_folder`); a folder per
language unless `--layout language-suffix`. Options: `--format DOCX` (only
some kinds), `--include-subfolders`, `--exclude drafts`.

Each script waits and reports every language. It can stop first with a
question: `TM_CHOICE_NEEDED` (`choices`: ask, then pass `--tm-name`) or
`TM_NEEDED`. If it times out, run the same command again: it reconnects,
nothing is charged twice.

### 3. Check and polish (only if asked) ⏸

`translate_document.py` returns a `translation` for each result; pass it on.
Each of these spends credits: ask first.

```bash
python3 scripts/quality_report.py --translation <translation> [--scope unverified]
python3 scripts/proofread.py --translation <translation>
python3 scripts/back_translate.py --translation <translation>
```

- **Quality report:** a score, a pass/fail band and the worst lines, each
  error explained with a `better` version. To fix them in the document:
  `quality_report.py --translation <t> --apply-fixes all|4,9 --out ./fixed.docx`.
- **Proofreading:** a suggested correction per line, with the reasons. Show
  them; apply only the ones the user accepts:
  `proofread.py --translation <t> --apply 3,7|all --out ./fixed.docx`.
- **Back-translation:** each translated line put back into the source
  language, so someone who can't read the translation can check its meaning.

Lines are named by number; relay suggestions as before → after.

## Rules

- **Show names, never ids.** Give each file with its language.
- **Ask before spending credits**, and at every ⏸.
- **Never invent a memory name.** Use what `list_tms.py` printed.
- **One command per request.** Several languages or files go in one call, not a loop.
- **Apply only what the user accepted.** Proofreading and fixes change the document.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.
`partial` means some languages failed: their `error` says why; running the same
command again retries only those.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow document translation for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
| 5 | Timed out | Still translating: run the same command again |
| 6 | File not found | Ask for the right path |
