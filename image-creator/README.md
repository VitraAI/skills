# image-creator

An agent skill that generates images from a text prompt using the Vitra Universe
Image Creator API, edits them in plain language, and files them into the
organization's Drive.

Drop this folder into your agent runtime's skills directory. The agent reads
`SKILL.md` and drives the scripts on its own — in normal use you don't run
anything by hand.

## What it does

1. `generate_image.py` — a prompt in, a finished image URL out. Synchronous.
2. `edit_image.py` — "make the background darker" against an image you already
   generated. Produces a new image derived from the original, so edits chain.
3. `save_to_drive.py` — file a generated image into the org's Drive.
4. `list_brand_kits.py` — the org's saved brand kits.
5. `brand_kit.py` — resolve a brand kit for a domain. Checks the org's saved
   kits **first** and only extracts from the live site when none matches, so a
   domain that already has a kit costs no extra model call.

   ```bash
   python3 scripts/brand_kit.py --domain vitra.ai
   # -> {"resolved":"existing","name":"Vitra.ai","primary_colors":["#8143FD",…],
   #     "prompt_fragment":"brand colors #8143FD, …. visual style: modern, …"}
   ```

   Append `prompt_fragment` to a `generate_image.py --prompt` to render on-brand.
   Add `--save` to persist a freshly extracted kit.

## Setup

**One environment variable** must be present in the process the agent runs in:

| Var                      | What                                                                                                                                                                                       |
| ------------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| `VITRA_UNIVERSE_API_KEY` | A Vitra API key (starts `uvk_`) — see **Getting a key** below. Bound to ONE organization, acting with its creator's role there — that member needs `translate_photo.image_creator` create/read. |

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
image-creator/
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
python3 scripts/generate_image.py --prompt "a red bicycle on a white background"
# -> stdout JSON with "status": "completed" and an "image_url"
```

Then chain an edit against the `creation_id` it returned:

```bash
python3 scripts/edit_image.py --creation-id "<creation_id>" --instructions "make it blue"
```

Outcomes:

- **Exit 0**, final stdout line is JSON — wired up correctly.
- **Exit 2**, `Missing required env var` — the key is not set.
- **Exit 3**, `auth rejected` — key wrong/expired, or its creator lacks
  `translate_photo.image_creator` in the org the key is bound to.

## Requirements

- Python 3, standard library only — no `pip install`, no build step.
- Outbound HTTPS.

## Troubleshooting

| Exit | Meaning                                                          |
| ---- | ---------------------------------------------------------------- |
| 2    | `VITRA_UNIVERSE_API_KEY` is not set in the process environment    |
| 3    | Key rejected (401/403) — wrong, expired, or missing permission    |
| 4    | API error, or the model refused the prompt (rephrase, don't retry) |

Both `generate` and `edit` block until the image exists (up to 5 minutes) — a
slow response is not a hang, and re-running costs credits twice.

The full agent-facing contract is in `SKILL.md`.
