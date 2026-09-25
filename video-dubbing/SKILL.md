---
name: video-dubbing
description: >-
  Dubs a video into one or more languages using the Vitra Universe translate-video
  API. Use for "dub this video", "voice-translate a video", "add a Hindi voiceover",
  "make a Spanish version of this clip". Inputs are a local video file OR a public
  video URL, a source language, and one or more target languages. The run pauses
  for a speaker-by-speaker voice decision (keep each speaker's own voice, or pick
  a different one), is reviewed for blocking issues, then exported and downloaded
  one language at a time. Do NOT use for subtitles-only,
  audio-only files, or image/text translation — those are separate skills.
compatibility: >-
  Python 3, standard library only. Outbound HTTPS. One env var:
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization). The key is bound
  to one organization and acts with its creator's role there — that member needs
  translate-video create/read/update/export, translation-memory create/read, and
  (for single-line re-translate / re-voice) translate-video sync create.
metadata:
  skill-author: Vitra.ai
  version: "2.1"
  display-name: Video Dubbing
  category: Video
  tags: Video, Translation, Popular
  source: vitra
  added: "2026-09-09"
  updated: "2026-09-25"
---

# video-dubbing

Dubs a video via the Vitra Universe translate-video API, from upload to a
reviewed, verified download — without the browser. Every command prints ONE
line of JSON on stdout with a `next_action`; follow it.

| Stage | Command | What it does |
|---|---|---|
| Start | `dub_video.py` | upload (or reuse identical bytes), start the run — or reconnect to the run already made for this file — and stop at the speaker-voice gate |
| Voices | `resume_dub.py` | apply each speaker's voice, generate, stop at `review_ready` (never exports) |
| Review | `inspect_process.py`, `get_card_media.py` | state, cards, settings, background jobs, one line's audio |
| Correct | `patch_cards.py` | text, timing, emotion, rate, Keep Source, lip-sync, review status, volume |
| Restructure | `card_ops.py` | split / merge / add / delete lines, speakers, a speaker's voice, re-translate or re-voice one line, subtitle lines |
| Re-voice | `regenerate_cards.py` | new audio for chosen / stale / missing cards only |
| More languages | `add_language.py` | add a language to the SAME dub, reusing each speaker's voice |
| Issues | `list_issues.py`, `fix_issues.py` | what blocks export; bounded repair (the editor's "Fix all issues") |
| Deliver | `export_dub.py`, `download_export.py` | render one reviewed language; download and verify it |
| Recover | `retry_dub.py`, `run_manifest.py`, `list_assets.py` | resume a failed run; the local run record; find earlier uploads/dubs |

Between Start and Voices, **ask the caller what to do with each speaker's voice**
(unless their answer is already on record). Text the caller did not approve is
never changed silently: every edit reports before → after.

## Critical

- **One env var:** `VITRA_UNIVERSE_API_KEY` — a `uvk_` key for one Vitra
  organization. If it is missing, stop and show the caller BOTH
  setup options (see "When the key is missing"). Never echo the key.
- **The organization comes from the key.** It is bound to one org at creation —
  never ask the caller which org, and never pass one.
- **ALWAYS ask which Translation Memory to use when more than one covers the
  language pair.** Run `list_tms.py` first and put the choice to the caller —
  never pick silently. Picking wrong writes the wrong wording into a memory the
  whole organization reuses, and that is not visibly undone later.
- **Never show the caller any id or UUID.** Organization ids, job ids, process
  job ids, process ids, speaker ids beyond "Speaker 1 / Speaker 2" — all
  internal. Refer to things by name and by language. The final reply contains
  only labelled download links or file paths.
- **A human decision at the voice gate.** `dub_video.py` intentionally stops
  there. Ask the caller per speaker (unless the run record already has their
  answer), then run `resume_dub.py`.
- **Export is a separate, reviewed step.** Nothing renders until `export_dub.py`,
  and it refuses while issues or stale audio remain. Never pass `--force` to get
  past a refusal the caller has not accepted.
- **Edits are shown, not hidden.** Relay every before → after a command reports.
  Always pass the `revision` you reviewed; on a "transcript changed" refusal,
  re-read and redo — never overwrite someone else's edit.
- **Polling is the scripts' job.** Commands wait in Python with backoff; do not
  loop on status yourself.
- **Language keys, not names.** Use the key from `list_languages.py` (e.g.
  `hindi_india`, `spanish_spain`). The API rejects display names.
- **Source language is required** — the video's spoken language, as a key from
  `list_languages.py`. There is no auto-detect; ask the caller.
- **Input is a local file OR an http(s) URL** — both are uploaded through the
  API (a URL is downloaded first). Reject other schemes.
- **Never fabricate results.** On a non-zero exit, tell the caller in plain
  terms what failed (see `references/troubleshooting.md`); do not paste ids or
  raw stderr.

## Step 1: Verify the key

```bash
[ -n "$VITRA_UNIVERSE_API_KEY" ] && echo OK || echo MISSING
```

If MISSING:

```bash
export VITRA_UNIVERSE_API_KEY=<uvk_... key for one Vitra organization>
```

## Step 2: Collect inputs

| Input           | Form                                   | Example                              |
| --------------- | -------------------------------------- | ------------------------------------ |
| Source          | local file path OR http(s) video URL   | `./demo.mp4`, `https://x.com/v.mp4`  |
| Source language | the video's spoken language             | English (US)                        |
| Target language | one or more                            | Hindi, Tamil                        |

Resolve BOTH source and target languages to keys with:

```bash
python3 scripts/list_languages.py
```

Ask the caller for the source language (the video's spoken language) — it is
required; there is no auto-detect. If no source or no target language, ask —
do not guess.

## Step 2b: Translation Memory — list, then ask

A TM holds the organization's approved wording. Reusing one keeps names, tone
and terminology identical to what they've dubbed before; without one, every run
is translated fresh and the same phrase can come out differently.

Check what covers this language pair **before** starting the dub:

```bash
python3 scripts/list_tms.py --source-language english_united_states --target-language hindi_india
```

Then act on what came back:

- **Several listed → ASK.** Show the caller the TM names and let them pick;
  offer "none" and "make a new one" as real options. Pass their choice, exactly
  as listed, to `dub_video.py --tm-name`. Do not pick for them — two TMs for one pair
  usually means different clients or shows, and choosing wrong quietly
  contaminates a memory with the wrong wording.

  > I found two translation memories for English → Hindi:
  > **Acme Marketing** and **Acme Legal**. Which should I use — or neither?

- **Exactly one → use it, and say so** in one line.

  > Using the **Acme Marketing** translation memory.

- **None listed → say nothing and continue.** Omit `--tm-name`: the server
  finds-or-creates the TM for this language pair automatically (a non-default
  `--tm-provider` is created by `dub_video.py` instead).

The auto-created TM is named `dub · <source> → <targets>` — named after the
LANGUAGES, not the video — so repeat dubs of the same pair share one memory
instead of each spawning a throwaway.

`list_tms.py` filters on the **target** language, not the source: VitraTM
memories are multi-source, so a TM created for a different source language still
serves this run. A listed TM whose source looks "wrong" is still valid.

### Which provider?

Only ask when there is a real choice. Check first:

```bash
python3 scripts/list_providers.py
```

- **One line on stdout** (the usual case — only VitraTM) → **don't ask.** Use
  it silently. Offering a choice of one wastes the caller's time.
- **Two or more** → ask, in the same breath as the TM question:

  > This organization has both **VitraTM** and **Phrase** connected. Which
  > should I use for this translation?

Pass the answer as `--tm-provider`. Anything the script printed to *stderr* is
NOT connected for this org — never offer it, and never suggest they "switch to
Phrase" as a fix.

The two differ in one way that matters here: **VitraTM memories are
multi-source** (one memory serves any source language), **Phrase memories are
tied to their source language**.

## Step 3: Phase 1 — start the dub, stop at the voice gate

```bash
python3 scripts/dub_video.py \
  --source-language "<source-lang-key>" \
  --url "<video-url>" \
  --target-language "<lang-key>"          # repeat --target-language per language
```

(or `--file "<local path>"` instead of `--url`.)

- **Emotion detection is on** (each line's emotion is detected and voiced; still
  editable per card). Pass `--no-emotion-detection` only if the caller asks for
  neutral delivery.
- **It never starts the same dub twice.** Same file (by content) + same
  languages → it reconnects to the existing run (from this machine's run
  record, or the server) instead of publishing. If that run is already past the
  voices it prints `"status": "review_ready"` — go to Step 6. `--new-run` forces
  a fresh dub; only when the caller explicitly wants one.

Stdout, one line:

```json
{
  "status": "awaiting_voices",
  "job_id": "<internal handle — do not show the caller>",
  "task_identifier": "INSTANT-VOICE-CLONING-ENGINE",
  "source_language": "english_united_states",
  "target_languages": ["hindi_india"],
  "speakers": [
    { "speaker_id": "0", "label": "Speaker 0", "gender": "male",
      "preview": { "st": 3.1, "et": 6.4 } }
  ],
  "saved_cloned_voices": [
    { "voice_id": "<internal>", "name": "John (Q3 webinar)", "gender": "male",
      "preview_url": "https://...", "supported_languages": ["hindi_india"] }
  ],
  "checkpoint": "~/.vitra/video-dubbing/runs/<job>.json"
}
```

## Step 4: Ask the caller about each speaker's voice

Diarization labels speakers per-video; the API does **not** know a speaker
appeared in an earlier dub. But the org's previously created clone voices come
back in `saved_cloned_voices`. If any exist, present them by name:

> _"2 speakers detected. You have saved cloned voices: **John (Q3 webinar)**
> (male), **Priya** (female). For each speaker, do you want a fresh clone of
> their own voice, or one of the saved voices?"_

For **every** speaker (as "Speaker 1 / Speaker 2"), and **every** target
language, get one choice:

- **`clone`** — fresh instant clone of that speaker's own voice. Default when
  the caller has no preference.
- **a saved voice** — the caller names one from `saved_cloned_voices`; use its
  `voice_id` internally. This is how a returning speaker keeps a prior voice.
- **`keep`** — leave whatever the gate already assigned (rare).

Build a `--voice-map` JSON object keyed by `speaker_id`:
`{ "0": { "hindi_india": "clone" }, "1": { "*": "<voice_id>" } }`
(`"*"` covers every target language for that speaker). Omitted speakers/langs
follow `--voice-mode`: `clone` (default) or `library_auto` (keep the library
voice the gate picked).

The decision is saved in the run record and reused — by a re-run of
`resume_dub.py` and by `add_language.py` for later languages — so the caller is
asked once. A saved voice is matched by its **id**, never by a similar name.
If a chosen voice cannot speak a target language, ask; never substitute.

## Step 5: Phase 2 — resume to review

```bash
python3 scripts/resume_dub.py \
  --job-id "<job_id from Step 3>" \
  --voice-map '{"0":{"hindi_india":"clone"}}'
```

Stdout: `{ "status": "review_ready", "job_id", "target_languages",
"next_action": "inspect_process", "checkpoint" }`. Re-running it after an
interruption picks the run up; it never submits voices twice.
`"status": "failed"` → **Step 12**.

## Step 6: Review the source first

A later language is translated from the SOURCE transcript, so correct it before
adding languages.

```bash
python3 scripts/inspect_process.py --job-id "<job>" --cards english_united_states
```

Keep the printed `revision`. Fix wording or timing of the source line:

```bash
python3 scripts/patch_cards.py --job-id "<job>" --language english_united_states \
  --revision <rev> --edits '[{"card_id":"<id>","text":"corrected line"}]'
```

`affected_languages` lists dubbed languages translated from the old text —
re-translate those lines (`card_ops.py retranslate`, then `speak`). Structure
fixes (a line that should be two, two that should be one, wrong speaker) are
`card_ops.py split | merge | assign-speaker | add-speaker`.

## Step 7: Add the remaining languages to the SAME dub

```bash
python3 scripts/add_language.py --job-id "<job>" --language tamil_india \
  --expected-revision <rev>
```

Each speaker keeps their voice (their clone, or the saved choice). If a speaker
has none it stops with `VOICE_DECISION_NEEDED` — ask the caller, pass
`--voice-map`. `--expected-revision` refuses if the source changed after the
review. Never publish a second dub for another language.

## Step 8: Review each dubbed language

```bash
python3 scripts/inspect_process.py --job-id "<job>" --cards hindi_india
python3 scripts/get_card_media.py --job-id "<job>" --card-id "<id>" --language hindi_india
```

Propose changes to the caller, then apply them with `--revision`:

```bash
python3 scripts/patch_cards.py --job-id "<job>" --language hindi_india --revision <rev> \
  --edits '[{"card_id":"<id>","text":"...","emotion":"calm"},
            {"card_id":"<id2>","start":12.4,"end":15.1},
            {"card_id":"<id3>","rate":1.1},
            {"card_id":"<id4>","review_status":"a"}]'
```

- Everything is validated first (emotion vocabulary, rate 0.5–2.0, timing inside
  the video and not overlapping neighbours); one bad edit changes nothing.
- A **text** change removes that line's audio on the server (`audio_cleared`;
  the line then shows "No Audio") → `regenerate_cards.py --missing`. An
  **emotion** change keeps the old clip (`audio_stale`) →
  `regenerate_cards.py --stale`. Or `card_ops.py speak` for one line —
  optionally in another voice.
- A card that should play the original audio: `"keep_source": true`. That is a
  deliberate exception, not a fix for missing audio.
- A refusal because the transcript changed means someone else edited it:
  nothing was saved. Re-inspect and redo the edit — never force it.
- A whole speaker's voice for one language: `card_ops.py speaker-voice`, then
  `regenerate_cards.py --missing`.

## Step 9: Issues — list, repair within budget

```bash
python3 scripts/list_issues.py --job-id "<job>" --language hindi_india
python3 scripts/fix_issues.py  --job-id "<job>" --language hindi_india   # if blocked
```

`fix_issues` is the editor's "Fix all issues", bounded (`--budget`, default 1):
missing audio only → re-voices exactly those cards; rate problems → autofix
(may shorten a translation to fit, and re-voices what it changed). It reports
every value changed; **show `approved_text_changed` to the caller.** Timing or
content errors it cannot fix are left in `remaining_errors` for `patch_cards` /
`card_ops`. An empty issue list is not a quality review — it only means nothing
blocks the render.

## Step 10: Export and download — one language at a time

```bash
python3 scripts/export_dub.py --job-id "<job>" --language hindi_india --revision <rev>
python3 scripts/download_export.py --export-id "<export_id>" \
  --out ./dub-hindi_india.mp4 --job-id "<job>"
```

`export_dub` refuses (never renders) while blocking errors remain, while cards
still speak an old line, or if the transcript changed after `--revision` was
reviewed. The same version is never rendered twice — a re-run returns the
existing export. `download_export` resumes an interrupted download, refreshes
an expired link for the SAME export, and verifies the file (video + audio
streams, duration, decode at start/middle/end with ffmpeg; MP4 structure
without it — reported as `media_check`).

## Step 11: Reply

Per language: the downloaded file path (or the export link if asked), labelled
by language name. Say what was changed during review, anything left unresolved,
the `media_check` level, and the credit balance from `inspect_process` if the
caller cares about usage. Links expire. No ids.

## Step 12: Recovery

- **Run failed** → `retry_dub.py --job-id`: resumes at the failed step; finished
  steps are not re-run or re-charged. Never publish a new dub to recover. A
  second failure is reported, not retried again.
- **Anything interrupted** (timeout, closed session) → re-run the SAME command;
  every command reconciles instead of repeating paid work.
- **New session / unsure where a run is** → `run_manifest.py list`, then
  `run_manifest.py validate --job-id` for the drift and the next step.
- **"Have we dubbed this before?"** → `list_assets.py --file <video>`.

On any non-zero exit, stdout is `{"status":"failed","error":{code, message,
retryable},"request_id"}`: explain `message` plainly, quote `request_id` only
for support. See `references/troubleshooting.md`; every command's endpoint is
in `references/capabilities.md`.

## When the key is missing

The script exits 2 and prints the setup guidance. Relay BOTH options — the
right one depends on how this agent is run, and the caller knows that better
than you do:

1. **An environment variable** in the process this agent runs in:
   `export VITRA_UNIVERSE_API_KEY=uvk_...`
   In a terminal that is a shell export; for a desktop or hosted agent it is
   that runtime's env/config setting — a terminal export does NOT reach it.
2. **A `.env` file at the root of this skill folder** (beside `SKILL.md`),
   containing `VITRA_UNIVERSE_API_KEY=uvk_...`. The scripts read it
   automatically, and it is gitignored.

If they have no key at all, tell them to ask whoever administers their Vitra
organization. Do not offer to mint one yourself, and never echo a key back.

## Before Marking Complete

- [ ] Voices were decided by the caller (or reused from the run record).
- [ ] The source was reviewed before languages were added; later languages were
      added to the SAME dub.
- [ ] Every edit's before → after was shown; `approved_text_changed` (if any)
      was shown; no `audio_stale` cards remain for an exported language.
- [ ] `list_issues` was clean for each exported language, and `export_dub` ran
      with the reviewed `--revision`.
- [ ] `download_export` succeeded, and its `media_check` level was reported.
- [ ] The reply has labelled files/links, the unresolved items — and no ids.

## Requirements

- Python 3, standard library only. No `pip install`, no build step.
- Outbound HTTPS.
- Optional: `ffmpeg`/`ffprobe` on PATH for full download verification.
- The scripts send `X-Client-Source: agent`, create no `__pycache__`, and write
  only: the downloads you ask for, a temp copy of a `--url` source (removed on
  exit), and the run record in `~/.vitra/video-dubbing/runs/` (no key, no
  signed links).
