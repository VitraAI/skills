---
name: video-subtitles
description: >-
  Makes subtitles from a video with the Vitra Universe API: transcribes it into
  timed subtitles (optionally following a script), lets the user review and
  correct lines, adds translated subtitle languages, downloads them as SRT, VTT,
  TXT and other formats, and renders the video with subtitles burned in. Use it
  whenever the user wants captions for a video — "subtitle this video", "add
  Hindi captions to this clip", "give me an SRT for this", "burn the subtitles
  in" — even if they only say "captions". Not for translating a subtitle file
  on its own (subtitle-translation), dubbing or voice-over (video-dubbing), or
  text inside images.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs a
  Vitra sign-in (scripts/login.py opens the browser) or VITRA_UNIVERSE_API_KEY
  (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Video Subtitles
  category: Video
  tags: Video, Subtitles, Translation
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-28"
---

# Video Subtitles

Subtitles from a video, through the Vitra API. Every script
prints **one line of JSON**; three fields drive the flow:

- `status`: where things stand.
- `error.ask`, `suggestions`: what to ask or offer the user (relay them).
- `next_action`: the script to run next.

Scripts wait for their own jobs and print progress in the webapp's steps.
Never loop on status, and never show ids to the user.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: continue, but don't offer the steps in
`cannot`. `blocked`: stop and tell the user which steps their key can't do;
their Vitra admin can grant them. Key missing (exit 2): relay the setup lines.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The video | yes | Local path or public http(s) URL |
| Spoken language | yes | Ask. Key: `python3 scripts/list_languages.py <name>` |
| Script of what is said | no | `.srt .vtt .ass .ssa .txt`. Transcription follows it; a timed one keeps its cues |

The video is subtitled in its own language first; translated languages are
added after review (step 4). A subtitle file on its own, to translate, is the
subtitle-translation skill's job.

## The flow

```
- [ ] 1. Translation memory     (⏸ ask if several)
- [ ] 2. Start                  → subtitles ready for review
- [ ] 3. Review                 (⏸ show the lines; edit what the user asks)
- [ ] 4. Add languages          (⏸ which ones; spends credits)
- [ ] 5. Deliver                (⏸ file download, or burned-in video: spends credits)
```

### 1. Translation memory ⏸

A video's subtitles need a translation memory: it holds the wording every
later translation reuses. `start_subtitles.py` picks it:

- **One** exists: used, and the output names it. Say so.
- **Several:** it stops with `TM_CHOICE_NEEDED` and `choices`. Ask which, by
  name, then re-run with `--tm-name "<name>"`.
- **None:** it stops with `TM_NEEDED` and an `ask`. Ask it, then re-run with
  `--create-tm --target-language <key> --tm-context "<their answer>"`
  (optionally `--tm-engine gemini|azure`; gemini is the default and follows the
  style guide).

### 2. Start

```bash
python3 scripts/start_subtitles.py --file talk.mp4 --source-language <src> [--script talk.srt]
```

Uploads (reusing an identical earlier upload), starts the job and waits. Ends
with `review_ready`. Re-running the same command reconnects to the same job.
It can stop first to ask: `TM_CHOICE_NEEDED` or `TM_NEEDED`: ask
`error.ask`, then re-run with the answer.

### 3. Review ⏸

```bash
python3 scripts/inspect_subtitles.py --job-id <job> --lines <lang>
```

Show the numbered lines (100 at a time; `more` gives the next page). Change
only what the user asks. Lines are addressed by their number; pass the
`revision` just read if it isn't null:

```bash
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> [--revision <rev>] \
  --edits '[{"line":3,"text":"New line\nsecond row"},{"line":4,"start":12.5,"end":14}]'
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> --split 3 --at-word 6
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> --merge 3,4
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> --delete 3
```

Relay each `before → after` from `changes`. When `renumbered` is true, read
the lines again before the next change. Review the source before adding
languages: every translation is made from it.

### 4. Add languages ⏸

Confirm first: each language is translated and charged.

```bash
python3 scripts/add_subtitle_language.py --job-id <job> --language <tgt> [--language <tgt2>] \
  [--expected-revision <rev>]
```

They queue and run one at a time; it waits for all. `partial` means some
failed (listed in `failed`, already rolled back): run it again for those.
Then review each new language as in step 3.

### 5. Deliver ⏸

`inspect_subtitles.py` lists what's ready in `suggestions`; offer them as a
short numbered list and run one only after the user agrees (ask first when
`spends_credits` is true).

```bash
python3 scripts/download_subtitles.py --job-id <job> --language <lang> --format srt --out ./<name>.<lang>.srt
python3 scripts/burn_subtitles.py --job-id <job> --language <lang> [--resolution 1080]
python3 scripts/download_export.py --export-id <export> --out ./<name>.<lang>.mp4 --job-id <job>
```

Formats: `srt vtt dfxp xml stl edl txt txt-timed json`. Burning in renders the
original video once per language (only for a job made from a video).

Save a burned-in video to the Drive, stop a job, file it in a folder, sync
lines with the memory, or get them as a spreadsheet: `job_tools.py`
([commands](references/commands.md#job-controls-job_toolspy)).

## Rules

- **Ask, don't guess, at every ⏸.** Languages, memories and anything that
  spends credits are the user's choice.
- **Never invent a memory name or a language key.** Use what the scripts print.
- **Show names, never ids.** Keep ids for the next command.
- **One job per file.** To add languages, use step 4; never start a second job.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again. A
job that failed: `python3 scripts/retry_subtitles.py --job-id <job>` resumes it
from the failed step.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow translate-video for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
| 5 | Timed out | Still running: run the same command again |
| 6 | File unreadable or URL unreachable | Ask for a reachable file |

Every command and its output: [commands](references/commands.md).
