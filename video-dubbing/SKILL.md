---
name: video-dubbing
description: >-
  Dubs a video into other languages with the Vitra Universe API: uploads it,
  pauses so the user chooses each speaker's voice (their own cloned voice or
  another), generates the dub, lets the user review and correct it line by
  line, then exports and downloads one verified video per language. Use it
  whenever the user wants a video dubbed, voice-translated or localized — "dub
  this video into Hindi", "make a Spanish version of this clip", "add a French
  voiceover", "start a dubbing project for this webinar" — and whenever they
  want to fix, re-voice, add a language to, or export a dub they already have,
  even if they don't say "dub"; it can also burn subtitles into the dubbed
  video. A "dubbing project" is a dub, started here, not a board project. Not
  for subtitles without a voice-over (video-subtitles), audio-only files, text
  in images, or documents.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization). ffmpeg is
  optional (fuller download checks).
metadata:
  skill-author: Vitra.ai
  version: "3.3"
  display-name: Video Dubbing
  category: Video
  tags: Video, Translation, Popular
  source: vitra
  added: "2026-09-09"
  updated: "2026-09-28"
---

# Video Dubbing

Turns one video into dubbed videos, one per language, through the Vitra API.
Every script prints **one line of JSON**. Read three fields and nothing else
drives the flow:

- `status`: where things stand.
- `checkpoint`, `suggestions`: what to ask or offer the user (relay them).
- `next_action`: the script to run next.

Scripts wait for long jobs themselves (with backoff). Never loop on status.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

- `ready` or `unknown`: continue.
- `partial`: continue, but don't offer the steps listed in `cannot`.
- `blocked`: stop. Tell the user which steps their key can't do and that their
  Vitra admin can grant them. Don't try the job anyway.

If the key is missing, the script exits 2 with setup instructions: see
[troubleshooting](references/troubleshooting.md#the-key-is-missing).

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The video | yes | A local file path or a public http(s) URL |
| Spoken language | yes | Ask; there is no auto-detect. Get the key: `python3 scripts/list_languages.py <name>` |
| Target languages | yes | Keys from the same list (e.g. `hindi_india`), never display names |
| Translation memory | ask only if several fit | See step 1 |

Start with **one** target language. Add the rest after the first is reviewed
(step 6), so they are translated from the corrected source.

## The flow

Copy this checklist and tick it off:

```
- [ ] 1. Pick a translation memory      (⏸ ask if several)
- [ ] 2. Start the dub                  → stops for voices
- [ ] 3. Voices                         (⏸ ask per speaker)
- [ ] 4. Review the source lines        (⏸ show, fix what the user wants)
- [ ] 5. Review each language           (⏸ show suggestions, apply fixes)
- [ ] 6. Add the other languages
- [ ] 7. Export and download            (⏸ confirm, it spends credits)
```

### 1. Translation memory

```bash
python3 scripts/list_tms.py --source-language <src> --target-language <tgt>
```

⏸ **Several listed:** ask which to use, by name, and offer "none" too. The
wrong one writes the wrong wording into a memory the whole organization reuses.
**One:** use it and say so. **None:** say nothing; the server creates one for
this language pair.

### 2. Start

```bash
python3 scripts/dub_video.py --file <path> --source-language <src> \
  --target-language <tgt> [--tm-name "<name>"]
```

A video already in the Vitra Drive: `--drive-file "Launch video.mp4"` instead of
`--file` (no upload). Stop, file, sync with the memory, change delivery or
background volume, or get every line as a spreadsheet: `job_tools.py`
([commands](references/commands.md#job-controls-job_toolspy)).

Uploads (or reuses an identical earlier upload), starts the dub, waits, and
stops at `"status": "awaiting_voices"` with the speakers. If the user has a
script of what is said (`.srt .vtt .ass .ssa .txt`), add `--script <file>`:
transcription follows it. Running it again never
starts a second dub for the same file and languages; it reconnects.

### 3. Voices ⏸

Ask once, per speaker ("Speaker 1", "Speaker 2", by label, never an id):
**keep their own voice** (`clone`, the default) or **one of the saved voices**
listed in `saved_cloned_voices` (by name). Then:

```bash
python3 scripts/resume_dub.py --job-id <job> --voice-map '{"1":{"*":"clone"}}'
```

It waits and stops at `review_ready`. The choice is remembered for later
languages. Details: [voices and memories](references/voices-and-memory.md).

### 4. Review the source ⏸

```bash
python3 scripts/inspect_process.py --job-id <job> --cards <source-language>
```

Show the user the numbered lines (text and timing; 50 at a time, `more` gives
the next page). Fix only what they ask for, naming lines by number, with the
`revision` you just read (leave it out if it is null):

```bash
python3 scripts/patch_cards.py --job-id <job> --language <lang> --revision <rev> \
  --edits '[{"line":3,"text":"corrected line"}]'
```

Show every `before → after` it reports. Splitting, merging or re-assigning a
line, fixing how a word is pronounced, or typing a line in another script from
Latin letters: [editing](references/editing.md).

### 5. Review each language ⏸

```bash
python3 scripts/inspect_process.py --job-id <job>
```

Relay its `suggestions` to the user as a short numbered list, in order: each
has a plain sentence (`do`), a reason (`why`) and the command (`run`). Typical
ones: generate missing speech, re-voice lines, fix blocking issues, review
unchecked lines, export. Run one only after the user agrees, and always ask
first when `spends_credits` is true. Repeat until only "Export" remains.

### 6. More languages

```bash
python3 scripts/add_language.py --job-id <job> --language <tgt> --expected-revision <rev>
```

Adds the language to the **same** dub with the same voices. If a speaker has no
voice to reuse it stops with `VOICE_DECISION_NEEDED`: ask, then pass
`--voice-map`. Then do step 5 for the new language.

### 7. Export and download ⏸

Confirm first: exporting renders a video and spends credits. Ask whether they
want subtitles burned in; if so add `--subtitles <lang>` (usually the same
language). A language with no subtitle lines is refused with `no_subtitles`:
making them costs credits too, so ask, then add `--generate-subtitles`.

```bash
python3 scripts/export_dub.py --job-id <job> --language <tgt> --revision <rev>
python3 scripts/download_export.py --export-id <export> --out ./<name>-<tgt>.mp4 --job-id <job>
```

`export_dub` refuses (`"status": "refused"`, nothing rendered) while issues or
out-of-date speech remain, or if the dub changed after `--revision`; follow its
`next_action`. It never renders the same version twice. `download_export`
verifies the file and reports `media_check` (`full` with ffmpeg, else `basic`).

## Replying to the user

Per language, give the file path or link labelled with the language name, what
changed during review, and anything left unresolved. Links expire. Mention if
`media_check` was only `basic`.

## Rules

- **Never show ids** (jobs, voices, exports). Say "line 3", "Speaker 1", "the
  Hindi version". Keep ids for the next command.
- **Ask at every ⏸, and only there.** Decisions about voices, memories, text
  and spending belong to the user; everything else has a safe default.
- **Show every change as before → after.** The user must never discover an
  edit they didn't approve, least of all to text they already approved.
- **Pass the `revision` you read.** If a command says the dub changed, re-read
  and redo; never force it, or you overwrite someone else's edit.
- **Never start a second dub to fix a problem.** `retry_dub.py` resumes a failed
  run without paying again for finished steps; re-running a command reconnects.
- **Don't bypass a refusal** (`--force`) unless the user explicitly accepts the
  reason the script gave.

## When something fails

Every failure prints `{"status": "failed", "error": {"code", "message",
"retryable"}}`. Explain `message` in plain words. `retryable: true` → run the
same command again. Anything else: [troubleshooting](references/troubleshooting.md).
A failed dub: `python3 scripts/retry_dub.py --job-id <job>`. Lost track of a
run: `python3 scripts/run_manifest.py list`.

## More detail (read when needed)

- [commands.md](references/commands.md): every script, its options and output.
- [voices-and-memory.md](references/voices-and-memory.md): voice choices, saved clones, memories, engines.
- [editing.md](references/editing.md): every kind of line edit, and what each does to the audio.
- [troubleshooting.md](references/troubleshooting.md): error codes and fixes.
- [capabilities.md](references/capabilities.md): which API route each script calls.
