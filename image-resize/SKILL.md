---
name: image-resize
description: >-
  Adaptively resizes an image to one or more target sizes using the Vitra
  Universe Adaptive Image API. Not a crop or a stretch — the model re-composes the
  artwork for each aspect ratio so the subject, text and margins still work. Use
  for "resize this banner for Instagram Story and LinkedIn", "make this creative
  fit 1080x1920", "I need this ad in three sizes". Input is a local image file OR
  a public image URL, plus one or more WIDTHxHEIGHT targets. Do NOT use for
  generating a new image from a prompt or for translating text inside an image —
  those are the image-creator and image-translation skills.
compatibility: >-
  Python 3, standard library only. Outbound HTTPS. One env var:
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization). The key is bound
  to one organization and acts with its creator's role there — that member needs
  translate_photo.design_agent create/read.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Adaptive Resize
  category: Design
  tags: Image
  source: vitra
  added: "2026-09-10"
---

# image-resize

Re-composes an image into other sizes via the Vitra Adaptive Image API.

**`resize_image.py`** runs the same four steps the webapp does: presign an
upload, PUT the bytes straight to S3, persist the asset, then queue one variant
per requested size and poll until each renders.

## Critical

- **One env var:** `VITRA_UNIVERSE_API_KEY` — a `uvk_` key for one Vitra
  organization. If it is missing, stop and show the caller BOTH
  setup options (see "When the key is missing"). Never echo the key.
- **The organization comes from the key.** Never ask the caller which org.
- **Never show the caller an adapt id.** Report labels, sizes and URLs.
- **Max 50MB** per image.
- **Sizes are exact pixels** (`1080x1920`), not ratios. For an image this org
  already translated, resizing by *ratio* belongs to the image-translation
  skill's `resize_translated.py`.
- **This is generative, not a crop.** Each size is re-rendered by a model, so it
  costs credits and takes time — don't request sizes the caller didn't ask for.
- **Partial success is normal.** If some sizes render and others fail, report the
  ones that worked rather than treating the whole run as failed. The script only
  errors when *every* size fails.

## Usage

One size:

```bash
python3 scripts/resize_image.py --file banner.png --size 1080x1920
```

Several, with labels (repeat `--size`):

```bash
python3 scripts/resize_image.py \
  --url "https://example.com/ad.png" \
  --size "1080x1920=Instagram Story" \
  --size "1200x627=LinkedIn" \
  --size "1080x1080=Square"
```

Prints:

```json
{"status":"completed","outputs":[{"label":"Instagram Story","dimension":"1080x1920","image_url":"…"}]}
```

Give the caller each label with its URL.

Options:

- `--name` — a display name for the asset in the dashboard.
- `--tier` — `FLASH` (default) renders inline. `PRO` stops at a human
  plan-approval gate, which an unattended run cannot clear — only pass it if the
  caller will approve in the dashboard.
- `--max-wait` — seconds before giving up (default 900). Many sizes need longer.

## Asking the caller

Ask only for **the target sizes**, if they aren't already stated. When the caller
names a platform rather than a number ("Instagram Story"), map it yourself to the
standard size and use the platform name as the label — don't make them look it up.

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
| 3 | Key rejected or lacks permission | Needs `translate_photo.design_agent` create/read. |
| 4 | Bad `--size` format, API error, or every size failed | `--size` must be `WIDTHxHEIGHT`. Report the message. |
| 5 | Timed out | Re-run, or raise `--max-wait` — many sizes at once take a while. |
| 6 | Source unreadable / too large | Ask for a file under 50MB or a reachable URL. |
