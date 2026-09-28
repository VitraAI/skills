---
name: dita-translation
description: >-
  Translates DITA maps (technical documentation: a .zip of .ditamap and .dita
  topics, with SVG images) into several languages with the Vitra Universe
  API, keeping every map, topic, tag and file name as it was, through the
  organization's translation memory; saves one translated zip per language,
  retries failed topics, and scores the result with a quality report whose
  fixes can be written back. Use it when the user has DITA or DITA-OT content
  — "translate our DITA docs into Japanese", "localize this ditamap",
  "translate the manual zip into German and French". Not for single Word or
  XML files (document-translation), subtitles or images.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API only.
  Needs a Vitra sign-in (scripts/login.py opens the browser) or
  VITRA_UNIVERSE_API_KEY (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: DITA Map Translation
  category: Localization
  tags: Documents, Translation, Technical writing
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# DITA Map Translation

Translates a whole DITA map, zipped, into one translated zip per language.
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
| The map as a .zip | yes | Maps, topics and images zipped together, up to 500 MB. A folder? Zip it first |
| Target languages | yes | Ask if not given. Names or codes both work: `Japanese`, `ja-JP` |
| Translation memory | when several fit | See step 1 |

The source language is the memory's. If the map is in another language, say
so before translating.

## The flow

```
- [ ] 1. Translation memory   (⏸ ask if several fit)
- [ ] 2. Translate            (⏸ confirm: spends credits) → one zip per language
- [ ] 3. Quality report       (only if the user wants: ⏸ spends credits)
```

### 1. Translation memory ⏸

```bash
python3 scripts/list_tms.py --target-language Japanese
```

**One fits:** use it and say so. **Several:** ask which, by name. **None:** the
user needs one first (in Vitra, or with the translation-memory skill).

### 2. Translate ⏸

Confirm the map, languages and memory: translation spends credits per word,
per language.

```bash
python3 scripts/translate_dita.py --file manual.zip --target-language Japanese \
  [--target-language German] [--tm-name "<memory>"] [--name "Q4 manual"] [--out-dir ./translated]
```

It uploads the map, waits for every topic, then saves
`<name>-<language>.zip` per language (`path`). A big map takes a while; if it
times out, run the same command again: it reconnects and nothing is charged
twice.

**Some topics failed** (`error.code: TOPICS_FAILED`): show the `failed` files
and why, then ask the `error.ask` question. Re-run the same command with
`--retry-failed` (translate them again) or `--allow-partial` (build the zip
now; those topics keep their original text).

### 3. Quality report (only if asked) ⏸

Each language in the result has a `translation`; pass it on. Spends credits:
ask first.

```bash
python3 scripts/quality_report.py --translation <translation> [--scope unverified]
```

Shows a score, a pass/fail band and the worst issues, numbered, each with its
topic `file`, what's wrong and a `better` version. To write fixes into the
map, apply only the ones the user accepts, and rebuild the zip:

```bash
python3 scripts/quality_report.py --translation <translation> --apply-fixes 1,3|all --out ./translated/manual-ja.zip
```

A fix that would break a topic's markup is skipped and counted (`skipped`).

## Rules

- **Show names, never ids.** Name each zip with its language; name topics by
  their path in the map.
- **Ask before spending credits**, and at every ⏸.
- **Never invent a memory name.** Use what `list_tms.py` printed.
- **One command for all languages.** Not one run per language.
- **Apply only what the user accepted.**

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow DITA map translation for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
| 5 | Timed out | Still translating: run the same command again |
| 6 | File not found, or the zip could not be saved | Ask for the right path; the zip is also in their Vitra Drive |
