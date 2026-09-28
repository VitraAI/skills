---
name: brand-kit
description: >-
  Manages the organization's brand kits in Vitra Universe: the colors, fonts,
  tone of voice, visual style and logo that Vitra's image creator applies to
  stay on brand. Reads a brand from its website, product images or a
  brand-book PDF, saves it as a kit, and lists, shows, edits or deletes kits
  by name. Use it when the user wants to set up or change their brand — "set
  up our brand kit from acme.com", "pull our brand from this style guide",
  "change our primary color to #0A7", "which brand kits do we have?". To make
  on-brand images, use image-creator.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API only.
  Needs VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Brand Kit
  category: Creative
  tags: Brand, Design
  source: vitra
  added: "2026-09-28"
  updated: "2026-09-28"
---

# Brand Kit

Sets up and edits brand kits. Every command is `scripts/brand_kits.py
<action>` and prints **one line of JSON**; `status`, `error.ask` (a question
for the user) and `next_action` drive the flow. Kits are named by their
name; there are no ids to show.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: continue without the steps in
`cannot`. `blocked`: stop and tell the user which steps their key can't do;
their Vitra admin can grant them. Key missing (exit 2): relay the setup lines.

## See kits

```bash
python3 scripts/brand_kits.py list [--search acme]
python3 scripts/brand_kits.py show --kit "Acme"
```

## Set up a kit

**From the brand's own material** ⏸ (spends credits: ask first):

```bash
python3 scripts/brand_kits.py extract --website acme.com
python3 scripts/brand_kits.py extract --image hero.png --image pack.jpg   # up to 6
python3 scripts/brand_kits.py extract --pdf brand-book.pdf
```

This only drafts the kit (`status: draft`). Show the colors, fonts, tone and
styles and ask whether to save it as is. To save, run the same command with
`--save` (and `--name "…"` to name it; image and PDF drafts also need
`--source-url` with the brand's website). If the user wants changes, save
with `create` instead and pass their values. Before extracting, `list` first:
the brand may already have a kit.

**From values the user gives:**

```bash
python3 scripts/brand_kits.py create --name "Acme" --source-url https://acme.com \
  --color "#8143FD" --color "#1A1A1A" [--heading-font Poppins] [--body-font Inter] \
  [--tone "Confident, warm"] [--style minimal --style modern] [--logo logo.png]
```

A kit needs a name, its website and 1–5 hex colors. Logos: PNG, JPG or SVG,
up to 2 MB.

## Change or delete a kit

```bash
python3 scripts/brand_kits.py update --kit "Acme" [--rename "Acme Co"] [--color … ] [--tone "…"] \
  [--heading-font …] [--body-font …] [--style …] [--website …] [--logo new.png | --remove-logo]
python3 scripts/brand_kits.py delete --kit "Acme"      # asks; then add --confirm
```

`--color` and `--style` replace the whole list: pass every value the kit
should keep. A kit's source website can't be changed.

## Rules

- **Show names, never ids.**
- **Ask before `extract`** (it spends credits) **and before `delete`** (it
  can't be undone; the script asks for `--confirm`).
- **Never invent brand values.** Save only what was extracted or what the
  user gave.
- `KIT_CHOICE_NEEDED` / `KIT_NOT_FOUND`: ask which kit, from `choices`.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow brand kits for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
| 6 | File not found | Ask for the right path |
