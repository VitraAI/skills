---
name: image-creator
description: >-
  Generates images from a text prompt using the Vitra Universe Image Creator API,
  then edits them in plain language and files them into the organization's Drive.
  Use for "create an image of...", "generate a banner/poster/ad creative",
  "make me a picture of...", and for follow-ups like "make the background darker",
  "remove the text", "save that to the drive". Both generate and edit are
  synchronous — one call returns a finished image URL. Do NOT use for translating
  text inside an existing image or for resizing an image to other aspect ratios —
  those are the image-translation and image-resize skills.
compatibility: >-
  Python 3, standard library only. Outbound HTTPS. One env var:
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization). The key is bound
  to one organization and acts with its creator's role there — that member needs
  translate_photo.image_creator create/read, plus brand_kit read (and create,
  to save a kit) for the brand-kit scripts.
metadata:
  skill-author: Vitra.ai
  version: "1.2"
  display-name: Image Creator
  category: Design
  tags: Image, Popular
  source: vitra
  added: "2026-09-10"
  updated: "2026-09-25"
---

# image-creator

Generates and edits images through the Vitra Universe Image Creator API.

- **`generate_image.py`** — a prompt in, a finished image URL out. Synchronous.
- **`edit_image.py`** — change an image you already generated, in plain language.
  Produces a *new* image (its own id) derived from the original.
- **`save_to_drive.py`** — file a generated image into the org's Drive.
- **`list_brand_kits.py`** — the org's brand kits by name, each with its colors,
  fonts, tone and a ready `prompt:` line.

## Critical

- **One env var:** `VITRA_UNIVERSE_API_KEY` — a `uvk_` key for one Vitra
  organization. If it is missing, stop and show the caller BOTH
  setup options (see "When the key is missing"). Never echo the key.
- **The organization comes from the key.** It is bound to one org at creation —
  never ask the caller which org, and never pass one.
- **Never show the caller a raw id.** Creation ids, asset ids and brand kit ids
  are plumbing — keep them for follow-up calls, and show the caller the image
  URL and what changed.
- **Both generate and edit block until the image exists** (up to 5 minutes). Do
  not poll them, and do not re-run on a slow response.

## Generate

```bash
python3 scripts/generate_image.py --prompt "a minimalist sale banner with a red gift box"
```

Prints `{"status":"completed","image_url":"…","creation_id":"…"}`. Give the
caller the `image_url`; hold the `creation_id` for edits.

Write the prompt out fully in the caller's own terms — subject, style, mood,
any text that must appear. A one-word prompt gives a generic result.

## Edit

Every "make it…" follow-up is an edit against the last `creation_id`:

```bash
python3 scripts/edit_image.py --creation-id <id> --instructions "make the background darker"
```

The result is a new image with a new `creation_id` — chain further edits against
*that* id, so the caller's changes accumulate.

## Save to Drive

Only when the caller asks to keep or file the image:

```bash
python3 scripts/save_to_drive.py --creation-id <id>
```

## Brand kits

If the caller mentions their brand, run `list_brand_kits.py`. Show the caller the
kit names (only names), and append the chosen kit's `prompt:` line to the
`--prompt` text. There is no separate brand flag on generate.

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

## Failure modes

| Exit | Meaning | Do this |
| --- | --- | --- |
| 2 | `VITRA_UNIVERSE_API_KEY` not set | Show the `export` line; stop. |
| 3 | Key rejected or lacks permission | The key's member needs `translate_photo.image_creator` create/read. |
| 4 | API error / model refused the prompt | Report the message; offer to rephrase. |

A refused prompt is usually a content-policy block — rephrase rather than retry
verbatim.
