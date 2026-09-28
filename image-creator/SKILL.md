---
name: image-creator
description: >-
  Generates images from a text prompt with the Vitra Universe Image Creator,
  edits them in plain language, applies the organization's brand kit, and saves
  them to the organization's Drive. Use it whenever the user wants an image,
  banner, poster, ad creative, social post visual or illustration made — "create
  an image of…", "make me a sale banner", "design a poster in our brand colors" —
  and for follow-ups like "make the background darker", "remove the text", "save
  that". Not for translating the text inside an existing image (image-translation)
  or resizing an image to other sizes (image-resize).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs a
  Vitra sign-in (scripts/login.py opens the browser) or VITRA_UNIVERSE_API_KEY
  (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Image Creator
  category: Design
  tags: Image, Popular
  source: vitra
  added: "2026-09-10"
  updated: "2026-09-25"
---

# Image Creator

Makes and edits images through the Vitra API. Every script prints one line of
JSON. Generating and editing wait until the image exists (up to 5 minutes):
don't poll and don't re-run a slow call.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: continue without the steps in `cannot`
(e.g. brand kits). `blocked`: stop and tell the user which steps their key can't
do; their Vitra admin can grant them. Key missing (exit 2): relay the setup
lines the script prints.

## The flow

```
- [ ] 1. Brand (only if the user mentions their brand)
- [ ] 2. Generate                       → show the image
- [ ] 3. Edit until the user is happy   (⏸ each round)
- [ ] 4. Save to the Drive              (only when asked)
```

### 1. Brand kit (optional)

```bash
python3 scripts/list_brand_kits.py
```

⏸ **Several kits:** ask which, by name. Append the chosen kit's `prompt:` line
to the prompt in step 2; there is no separate brand option.

**No kit, but the user gives their website:**

```bash
python3 scripts/brand_kit.py --domain acme.com [--save]
```

It reuses a saved kit for that domain before extracting a new one (extracting
costs a model call). Append its `prompt_fragment` to the prompt. `--save` keeps a
newly extracted kit for next time; ask first.

### 2. Generate

```bash
python3 scripts/generate_image.py --prompt "<subject, style, mood, any exact text>"
```

Write the prompt fully in the user's terms; a one-word prompt gives a generic
result. Returns `image_url` (show it) and `creation_id` (keep it).

### 3. Edit ⏸

Every "make it…" is an edit of the **latest** image:

```bash
python3 scripts/edit_image.py --creation-id <latest> --instructions "make the background darker"
```

It returns a new image with a new `creation_id`: edit that one next, so changes
build on each other. Show each result and ask if it needs more.

### 4. Save

Only when the user asks to keep or file it:

```bash
python3 scripts/save_to_drive.py --creation-id <id>
```

## Rules

- **Never show ids.** Show the image link and what changed; keep ids for the
  next command.
- **One question at a time.** Brand and edits are the user's call; everything
  else has a sensible default.
- **A refused prompt is usually a content-policy block.** Rephrase it with the
  user; don't retry the same words.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow image creation for their role |
| 4 | API error or refused prompt | The message; offer to rephrase |
