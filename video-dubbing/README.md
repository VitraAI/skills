# video-dubbing

An agent skill that dubs a video into one or more languages using the Vitra
Universe translate-video API — from upload to a reviewed, verified download,
without opening the editor.

Drop this folder into your agent runtime's skills directory. The agent reads
`SKILL.md` and drives the scripts on its own — in normal use you don't run
anything by hand.

## What it does

1. Uploads the source video (a local file, or a public URL it downloads first) —
   or reuses the identical earlier upload and the dub already made from it.
2. Starts an instant-clone dub (emotion detection on) and pauses at the
   speaker-voice gate; the agent asks the caller per speaker.
3. Generates the dub and stops for review — nothing is rendered yet.
4. Reviews and corrects, card by card: text, timing, emotion, rate, Keep
   Source, lip-sync, review status, volume; split / merge / add / delete lines;
   speakers and voices; re-translate or re-voice single lines; subtitle lines.
5. Adds more languages to the same dub, reusing each speaker's voice.
6. Lists and repairs blocking issues (bounded, every change disclosed).
7. Exports one reviewed language at a time and downloads it, verified.

Failed runs resume from the failed step; interrupted commands reconcile instead
of repeating paid work. See `SKILL.md` for the agent-facing flow and
`references/capabilities.md` for every command's endpoints.

## Setup

**One environment variable** must be present in the process the agent runs in:

| Var                     | What                                                                 |
| ----------------------- | ------------------------------------------------------------------- |
| `VITRA_UNIVERSE_API_KEY` | A Vitra API key (starts `uvk_`) — see **Getting a key** below. It is bound to ONE organization and acts with its creator's role there — that member needs translate-video create/read/update/export (plus sync create for single-line re-translate / re-voice) and translation-memory create/read permission in that org. The org is resolved from the key, so nothing else is passed. |

### Where the key goes

The scripts look in two places, in this order:

**1. An environment variable** (wins if both are set):

```bash
export VITRA_UNIVERSE_API_KEY=uvk_your_key_here
```

⚠️ This must be set in the environment **the agent runs in** — not just your
terminal. Exporting in a shell does not reach Claude Desktop or a hosted agent;
set it wherever that process gets its environment.

**2. A `.env` file at the root of this skill folder** — beside `SKILL.md`:

```
video-dubbing/
├── SKILL.md
├── .env          ← here (gitignored)
└── scripts/
```

```bash
cp .env.sample .env
# then edit .env:
VITRA_UNIVERSE_API_KEY=uvk_your_key_here
```

Both `KEY=value` and `export KEY=value` are accepted.

### Getting a key

A key is minted per organization by someone who is a member of it:

```
POST /v1/api-keys
Header: organizationId: <org-uuid>
Body:   { "name": "image skills" }
```

The secret is returned **once** — store it immediately, it cannot be retrieved
again. The key inherits its creator's permissions in that one organization and
can never do more than they can. Ask your Vitra org administrator if you don't
have one.

Never hardcode the key into a script, and never commit `.env`.

## Verify it works

With the key set, from this folder:

```bash
python3 scripts/list_languages.py
# -> one line per language key: "<key>  <label>"   (proves auth + connectivity)
```

Then a real dub against a short public video:

```bash
python3 scripts/dub_video.py \
  --source-language english_united_states \
  --url "https://example.com/short.mp4" \
  --target-language hindi_india
# -> stdout JSON with "status": "awaiting_voices"

python3 scripts/resume_dub.py --job-id "<job_id from above>"
# -> stdout JSON with "status": "review_ready"

python3 scripts/export_dub.py --job-id "<job_id>" --language hindi_india
python3 scripts/download_export.py --export-id "<export_id>" --out ./dub.mp4
```

Outcomes:

- **Exit 0**, final stdout line is JSON — wired up correctly.
- **Exit 2**, `Missing required env var: VITRA_UNIVERSE_API_KEY` — not set.
- **Exit 3**, `auth rejected` — the key is wrong/expired, or its creator lacks
  the required permission in the org the key is bound to.

## Requirements

- Python 3, standard library only — no `pip install`, no build step.
- Outbound HTTPS.
- Optional: `ffmpeg`/`ffprobe` on PATH, for full verification of downloads.
- Run state is kept in `~/.vitra/video-dubbing/runs/` (override with
  `VITRA_DUB_STATE_DIR`): ids, hashes, revisions and choices — never the key.

## Troubleshooting

| Exit | Meaning                                                            |
| ---- | ---------------------------------------------------------------- |
| 2    | `VITRA_UNIVERSE_API_KEY` is not set in the process environment    |
| 3    | Key rejected (401/403) — wrong, expired, or missing permission in the key's org |
| 4    | Other API error — bad language key, insufficient credits, etc.   |
| 5    | Polling timed out — the work continues; re-run the same command   |
| 6    | Source download/read failed — bad URL, unreachable, or missing file |

On failure stdout carries `{"status":"failed","error":{code,message,retryable},"request_id"}`.
The full agent-facing contract is in `SKILL.md`; details in `references/`.
