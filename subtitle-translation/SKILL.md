---
name: subtitle-translation
description: >-
  Translates subtitle files (SRT, VTT, ASS, SSA) into one or more languages
  with the Vitra Universe API, keeping every cue's timing, and saves one file
  per language as SRT, VTT, TXT or another format. One command in, files out;
  lines can then be reviewed and corrected by number, and more languages added
  to the same job. Use it whenever the user wants captions or a subtitle file
  translated — "translate this SRT into Spanish and French", "make German
  captions from these", "convert and translate our VTT". Not for making
  subtitles from a video (video-subtitles), dubbing (video-dubbing), or
  documents (document-translation).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Subtitle Translation
  category: Localization
  tags: Subtitles, Translation, Popular
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Subtitle Translation

Translates a subtitle file and saves the translated files. Each script prints
**one line of JSON**; `status`, `error.ask` (a question for the user) and
`next_action` drive the flow. Scripts wait for their own jobs.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: don't offer the steps in `cannot`.
`blocked`: stop and tell the user which steps their key can't do. Key missing
(exit 2): relay the setup lines.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The subtitle file | yes | `.srt .vtt .ass .ssa`, local or a public URL |
| Its language | yes | Ask. Key: `python3 scripts/list_languages.py <name>` |
| Target languages | yes | Ask. Keys the same way |
| Output format | no | `srt` (default), `vtt`, `txt`, `txt-timed`, `dfxp`, `stl`, `json` … |
| Translation memory | no | Offer only if the user cares about terminology: `list_tms.py` |

## The flow

```
- [ ] 1. Translate   (⏸ confirm: spends credits) → one file per language
- [ ] 2. Review      (only if the user asks) → corrected files
```

### 1. Translate ⏸

```bash
python3 scripts/translate_subtitles.py --file talk.srt --source-language <src> \
  --target-language <tgt> [--target-language <tgt2>] [--format vtt] [--tm-name "<memory>"]
```

Uploads, translates every language with each cue's timing kept, waits, and
saves `files` (one per language) in `--out-dir` (default `./translated`).
Without `--tm-name` the memory for the language pair is found or created.
Re-running the same command reconnects instead of translating again.

### 2. Review (only if asked)

```bash
python3 scripts/inspect_subtitles.py --job-id <job> --lines <tgt>
python3 scripts/edit_subtitles.py --job-id <job> --language <tgt> [--revision <rev>] \
  --edits '[{"line":3,"text":"Better wording"}]'
python3 scripts/download_subtitles.py --job-id <job> --language <tgt> --format srt --out ./talk.<tgt>.srt
```

Lines are named by number. Relay each `before → after`, then download the
corrected file. More languages later, on the same job:
`add_subtitle_language.py --job-id <job> --language <key>` (spends credits).

## Rules

- **Ask before spending credits.** Say which languages you'll translate.
- **Show files and languages, never ids.** Keep ids for the next command.
- **One command for every language**, not one run per language.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again. A
failed job: `python3 scripts/retry_subtitles.py --job-id <job>`.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow translate-video for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
| 5 | Timed out | Still translating: run the same command again |
| 6 | File unreadable or URL unreachable | Ask for a reachable file |
