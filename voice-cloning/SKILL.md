---
name: voice-cloning
description: >-
  Clones a voice from one to five audio samples with the Vitra Universe API,
  so the organization can speak any text or dub any video in that voice. Use
  it whenever the user wants a custom or cloned voice — "clone my voice from
  this recording", "make a voice from these samples of our narrator", "which
  cloned voices do we have?" — and only for a voice they own or have the
  rights to. Not for generating speech (text-to-speech) or dubbing
  (video-dubbing), which then use the cloned voice.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.1"
  display-name: Voice Cloning
  category: Audio
  tags: Audio, Voice
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-28"
---

# Voice Cloning

Creates a cloned voice from audio samples. Each script prints **one line of
JSON**; `status` and `next_action` drive the flow.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps
their key can't do. Key missing (exit 2): relay the setup lines.

## The flow

```
- [ ] 1. Consent   (⏸ the user owns the voice or has the rights)
- [ ] 2. Samples   (⏸ 1–5 clean recordings; a name for the voice)
- [ ] 3. Clone     (⏸ confirm: spends credits) → a ready voice
```

### 1. Consent ⏸

Ask plainly: is it their own voice, or do they have the speaker's permission?
Don't clone without a yes.

### 2. Samples ⏸

One to five audio files (`.mp3 .wav .m4a .aac .ogg .flac .webm`) of the same
person, speaking clearly with little background noise; a minute or more in
total works best. Ask what to call the voice.

### 3. Clone ⏸

```bash
python3 scripts/clone_voice.py --sample a.wav --sample b.wav --name "Priya narration" \
  [--language english_united_states] [--gender female] [--provider elevenlabs] \
  [--remove-background-noise]
```

Ends with `ready` and the voice's `preview_url`: share it. The voice now shows
in text-to-speech (`list_voices.py --cloned-only`) and in dubbing's voice
choices. `processing`: check later with `python3 scripts/list_cloned_voices.py`.

### Retry or delete a clone

```bash
python3 scripts/clones.py retry --voice "Priya"          # a failed clone, ⏸ paid
python3 scripts/clones.py delete --voice "Priya"         # asks; then add --confirm
```

## Rules

- **Never clone without consent.**
- **Show voice names, never ids.**
- **Ask before spending credits.**

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow the Video Playground for their role |
| 4 | API error, or not an audio file | Explain the message |
| 6 | Sample not found | Ask for the right path |
