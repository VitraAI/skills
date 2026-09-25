# image-translation

An agent skill that translates the text baked into an image — signage,
packaging, ad creatives, screenshots, menus — using the Vitra Universe Image
Translator API, and re-renders it in the target language with the original
layout preserved.

Drop this folder into your agent runtime's skills directory. The agent reads
`SKILL.md` and drives the scripts on its own — in normal use you don't run
anything by hand.

## What it does

`translate_image.py` performs the whole job in one call, mirroring the four
steps the webapp runs:

1. Uploads the image and analyzes it for text regions.
2. Waits for analysis to finish.
3. Translates the extracted text into the target language.
4. Waits for the re-rendered image and returns its URL.

The output is a new **image** with translated text set back into the original
layout — not a text transcript.

Two companion scripts:

- **`list_tms.py`** — the organization's Translation Memories, filtered to a
  language pair. A TM holds approved wording, so reusing one keeps terminology
  consistent with past translations. The agent shows these and asks which to use.

  ```bash
  python3 scripts/list_tms.py --source-language English --target-language French
  # image · English → French  English → French  [vitratm]
  ```

- **`resize_translated.py`** — re-render an already-translated image at another
  aspect ratio, reusing the translation (no re-analysis, no re-translation).

  ```bash
  python3 scripts/resize_translated.py --job-id "<job_id>" --aspect-ratio 9:16
  # -> {"status":"completed","image_url":"…","aspect_ratio":"9:16","version_number":2}
  ```

## Setup

**One environment variable** must be present in the process the agent runs in:

| Var                      | What                                                                                                                                                                                             |
| ------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `VITRA_UNIVERSE_API_KEY` | A Vitra API key (starts `uvk_`) — see **Getting a key** below. Bound to ONE organization, acting with its creator's role there — that member needs `translate_photo.image_translator` create/read. |

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
image-translation/
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
python3 scripts/translate_image.py --file poster.png --target-language French
# -> stdout JSON with "status": "completed" and an "image_url"
```

A public URL works too — it is downloaded, then uploaded:

```bash
python3 scripts/translate_image.py --url "https://example.com/sign.jpg" --target-language Hindi
```

Outcomes:

- **Exit 0**, final stdout line is JSON — wired up correctly.
- **Exit 2**, `Missing required env var` — the key is not set.
- **Exit 3**, `auth rejected` — key wrong/expired, or its creator lacks
  `translate_photo.image_translator` in the org the key is bound to.

## Requirements

- Python 3, standard library only — no `pip install`, no build step.
- Outbound HTTPS.
- Source images up to **10MB**.

## Troubleshooting

| Exit | Meaning                                                                |
| ---- | ---------------------------------------------------------------------- |
| 2    | `VITRA_UNIVERSE_API_KEY` is not set in the process environment          |
| 3    | Key rejected (401/403) — wrong, expired, or missing permission          |
| 4    | API error, or no readable text was found in the image                   |
| 5    | Polling timed out — re-run, or raise `--max-wait` for a dense image     |
| 6    | Source download/read failed — bad URL, unreachable, or over 10MB        |

The full agent-facing contract is in `SKILL.md`.
