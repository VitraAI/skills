---
name: translation-memory
description: >-
  Manages an organization's translation memory with the Vitra Universe API —
  the approved wording every Vitra translation reuses: translates short texts
  (UI strings, product copy) memory-first, looks up how a phrase was
  translated before, corrects entries, imports existing translations from TMX,
  XLIFF, Excel or CSV, creates memories, and shows glossaries and style
  guides. Use it whenever the user talks about terminology or consistency —
  "how do we translate 'checkout' in German?", "always translate X as Y",
  "load our old TMX", "translate these app strings with our memory", "set up a
  memory for Acme". Not for whole documents (document-translation).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Translation Memory
  category: Localization
  tags: Translation, Terminology
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Translation Memory

A translation memory holds the organization's approved wording; every Vitra
translation that uses it reuses and grows it. Each script prints **one line of
JSON**. Name memories exactly as `list_tms.py` prints them.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: don't offer the steps in `cannot`.
`blocked`: stop and tell the user which steps their key can't do.

## What the user wants → what to run

| The user wants | Run | Ask first? |
|---|---|---|
| Which memories exist | `list_tms.py [--target-language French]` | — |
| How a phrase is translated | `search_terms.py --tm-name "<memory>" --search "checkout" [--language de-DE]` | — |
| "Always translate X as Y" | `correct_term.py --tm-name "<memory>" --source-text "X" --target-language de-DE --target-text "Y"` | ⏸ show before → after |
| Short texts translated consistently | `translate_text.py --tm-name "<memory>" --text "…" [--text "…"] --target-language German` (or `--file strings.txt`, one per line) | ⏸ spends credits |
| Load existing translations | `import_terms.py --tm-name "<memory>" --file old.tmx [--status approved]` | ⏸ confirm the memory |
| A new memory | `create_tm.py --name "Acme web" --source-language en-US --target-language de-DE --context "<who it's for>"` | ⏸ ask the context sentence |
| Glossaries and style guides | `list_glossaries.py [--style-guide "<name>"]` | — |

## Notes

- **Several memories fit:** ask which, by name. The wrong one writes the wrong
  wording into a memory the whole organization reuses.
- **Corrections are for wording the user gave or approved.** `correct_term.py`
  prints `before → after`: relay it. It saves as `approved` unless told
  otherwise (`--status verified|unverified`).
- **`translate_text.py` results** say where each came from: `exact` (the
  memory), `fuzzy` (a close match) or `mt` (machine translation, now stored
  as unverified). Point out `mt` lines the user may want to review.
- **Creating a memory** needs one sentence on who it's for (the client or
  product, and the audience): ask it. Engine: `gemini` (default, follows the
  style guide) or `azure`.
- Languages: names (`German`) or codes (`de-DE`) both work.

## Rules

- **Never invent a memory name.** Use what `list_tms.py` printed.
- **Show names, never ids.**
- **Ask before spending credits or changing a shared memory.**

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.
`CONFLICT`: someone changed that entry meanwhile — search again, then redo.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow translation memories for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
| 5 | Timed out | Still working: check again later |
| 6 | File not found | Ask for the right path |
