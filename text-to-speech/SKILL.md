---
name: text-to-speech
description: >-
  Turns text into natural speech with the Vitra Universe API, in hundreds of
  catalog voices across languages or the organization's own cloned voices, and
  saves the audio files. Long text is split into passages that are generated
  together. Use it whenever the user wants text spoken or a voice-over made
  from a script — "read this out in a British male voice", "make an MP3 of
  this announcement in Hindi", "generate narration for these paragraphs", "say
  this in my cloned voice". Not for dubbing an existing video (video-dubbing)
  or creating a new voice from samples (voice-cloning).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Text to Speech
  category: Audio
  tags: Audio, Voice, Popular
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Text to Speech

Speaks text in a chosen voice and saves the audio. Each script prints **one
line of JSON**; `status`, `error.ask` and `next_action` drive the flow.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps
their key can't do. Key missing (exit 2): relay the setup lines.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The text | yes | In the request, or a `.txt` file. Blank lines separate passages (one audio file each) |
| Language | yes | Key: `python3 scripts/list_languages.py <name>` |
| Voice | yes | ⏸ step 1 |
| Delivery | no | `--emotion happy`, `calm`… where the voice supports it |

## The flow

```
- [ ] 1. Voice    (⏸ offer 3–5 with previews)
- [ ] 2. Speak    (⏸ confirm: spends credits) → audio files
```

### 1. Voice ⏸

```bash
python3 scripts/list_voices.py --language <key> [--gender female] [--keyword warm] [--cloned-only]
```

Offer a few by name with their `preview_url` and let the user pick. Keep the
chosen voice's `provider` and `voice_id`.

### 2. Speak ⏸

```bash
python3 scripts/speak.py --text "Welcome to Acme." --language <key> \
  --voice-id <voice_id> --provider <provider> --voice-name "<name>" [--name "Welcome"]
python3 scripts/speak.py --text-file script.txt --language <key> --voice-id <id> --provider <provider>
```

Generates every passage together, waits and saves `files` (one per passage) in
`--out-dir` (default `./speech`). Re-running the same command reconnects:
finished clips are kept, failed ones are made again.

## Rules

- **Ask before spending credits.** Say how many passages will be voiced.
- **Let the user choose the voice**; never pick one silently.
- **Show voice names, never ids.** Keep ids for the next command.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.
`partial`: some clips failed; running the same command again remakes only those.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow the Video Playground for their role |
| 4 | API error | Explain the message |
| 5 | Timed out | Still generating: run the same command again |
