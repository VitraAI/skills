---
name: lip-sync
description: >-
  Makes the lips in a video match a new audio track with the Vitra Universe
  API — a dubbed voice, a re-recorded line, a translated voice-over — and saves
  the rendered video. Use it whenever the user wants mouth movements matched to
  audio — "lip-sync this video to the Spanish audio", "make the lips match the
  new voice-over", "sync his mouth to this recording". Not for dubbing a video
  from scratch (video-dubbing, which can lip-sync its own export) or making the
  audio (text-to-speech).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Lip Sync
  category: Video
  tags: Video, Voice
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Lip Sync

Renders a video whose lips follow a given audio track. Each script prints
**one line of JSON**; `status` and `next_action` drive the flow. The script
waits for the render (it can take a while); never re-run to check.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps
their key can't do. Key missing (exit 2): relay the setup lines.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The video | yes | A local file with the speaker's face visible |
| The audio | yes | A local file: the speech the lips should match |
| Its language | yes | Key: `python3 scripts/list_languages.py <name>` |
| Speakers on screen | if more than one | `--speakers 2` |
| Model | no | `python3 scripts/list_lip_sync_models.py`: offer only `available` ones |

## Render ⏸

Confirm first: rendering spends credits.

```bash
python3 scripts/lip_sync.py --video clip.mp4 --audio spanish.wav --language spanish_spain \
  [--out ./clip.es.mp4] [--model <model>] [--speakers 2]
```

Uploads both files, renders, waits and saves the video (`path`). If it times
out, run the same command again: it reconnects to the same render.

## Rules

- **Ask before spending credits.**
- **Only lip-sync people who agreed to it**, or content the user has rights to.
- **Show file names, never ids.**

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow the Video Playground for their role |
| 4 | API error, or the render failed | Explain the message; a failed render can simply be run again |
| 5 | Timed out | Still rendering: run the same command again |
| 6 | File not found | Ask for the right path |
