---
name: document-translation
description: >-
  Translates documents and text with the Vitra Universe API, keeping the
  original layout and formatting: Word (.docx), PowerPoint (.pptx), Excel
  (.xlsx), CSV, PDF, HTML, JSON, XML, XLIFF and plain text, into one or more
  languages at once, through the organization's translation memory so approved
  terminology is reused. Use it whenever the user wants a file or text
  translated or localized — "translate this contract into German", "make a
  Spanish version of this deck", "localize our strings.json", "translate this
  paragraph into Japanese". Not for subtitles (subtitle-translation), text in
  images (image-translation) or video (video-dubbing).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API only.
  Needs VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
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
```

### 1. Translation memory ⏸

```bash
python3 scripts/list_tms.py --target-language French
```

**One fits:** use it and say so. **Several:** ask which, by name; the wrong one
writes the wrong wording into a memory the whole organization reuses. **None:**
the user needs one first: they can create it in Vitra (Translation Memory), or
with the translation-memory skill.

### 2. Translate ⏸

Confirm the file, languages and memory: translation spends credits per word.

```bash
python3 scripts/translate_document.py --file contract.docx \
  --target-language German --target-language French [--tm-name "<memory>"]
python3 scripts/translate_document.py --text "Welcome to Acme" --target-language Japanese
```

Options: `--out-dir` (default `./translated`), `--columns 1,3` (CSV: only
those columns, 0-based; ask which hold prose if unsure), `--keep-first-row`
(Excel: leave headings as they are).

It starts one translation per language and waits. `results` lists each
language with its file `path` (or `text`). It can stop first with a question:
`TM_CHOICE_NEEDED` (`choices`: ask, then pass `--tm-name`) or `TM_NEEDED`.
If it times out, run the same command again: it reconnects, nothing is
charged twice.

## Rules

- **Show names, never ids.** Give each file with its language.
- **Ask before spending credits**, and at every ⏸.
- **Never invent a memory name.** Use what `list_tms.py` printed.
- **One command per request.** Several languages go in one call, not a loop.

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
