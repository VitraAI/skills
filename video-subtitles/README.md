# video-subtitles

An agent skill that makes, translates and edits subtitles with the Vitra
Universe API — from a video or an existing subtitle file to reviewed subtitle
files, or a video with the subtitles burned in, without opening the editor.

Drop this folder into your agent runtime's skills directory. The agent reads
`SKILL.md` and drives the scripts on its own.

## What it does

1. **From a video:** transcribes it into timed subtitles in the spoken
   language (optionally following a script you already have: SRT, VTT, ASS,
   SSA or TXT).
2. **From a subtitle file:** translates it into the languages you choose,
   keeping every cue's timing.
3. Lets you review and correct lines by number — text, timing, split, merge,
   delete.
4. Adds more translated subtitle languages to the same job.
5. Downloads any language as SRT, VTT, DFXP, XML, STL, EDL, TXT or JSON, or
   renders the video with one language burned in.

Progress is reported in the same steps the Vitra webapp shows. Anything that
spends credits is confirmed with you first.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key for one Vitra organization) in the
environment the agent runs in, or put it in a `.env` beside `SKILL.md`:

```bash
cp .env.sample .env
# then edit .env:
VITRA_UNIVERSE_API_KEY=uvk_your_key_here
```

Keys are created in the Vitra webapp (Settings → API keys) by an organization
owner or admin. A key acts with its creator's role in that one organization.
Never commit `.env`.

## Verify it works

```bash
python3 scripts/check_access.py        # which steps this key can do
python3 scripts/list_languages.py hindi
```

## Requirements

Python 3.10+, standard library only, and outbound HTTPS to the Vitra API.
