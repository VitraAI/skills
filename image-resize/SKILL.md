---
name: image-resize
description: >-
  Re-composes an image into other sizes with Vitra Adaptive Image: each size is
  re-rendered by a model (not cropped), so a banner becomes a story, a square
  post or a LinkedIn image with the layout re-arranged to fit. Use it whenever
  the user wants an image in other dimensions or for other platforms — "resize
  this for Instagram stories", "make 1080x1920 and 1200x627 versions", "adapt
  this banner for all our social channels". Not for translating text in an image
  (image-translation, which also resizes images it translated by aspect ratio)
  or generating a new image (image-creator).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API only (no
  direct storage uploads). Needs a Vitra sign-in (scripts/login.py opens the
  browser) or VITRA_UNIVERSE_API_KEY (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Adaptive Resize
  category: Design
  tags: Image
  source: vitra
  added: "2026-09-10"
  updated: "2026-09-28"
---

# Adaptive Resize

Re-renders one image at one or more exact pixel sizes. The script uploads the
image to the organization's Drive through the Vitra API, queues one version per
size and waits until they render (15 minutes by default). It prints one line
of JSON.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps their
key can't do; their Vitra admin can grant them. Key missing (exit 2): relay the
setup lines it prints.

## The flow

```
- [ ] 1. Sizes   (⏸ ask only if none were given)
- [ ] 2. Resize  → show each size's link
- [ ] 3. Check, fix, save  (only if asked)
```

### 1. Sizes ⏸

Ask for the target sizes only if the request has none. Map platform names to
sizes yourself and keep the platform as the label ("Instagram Story" →
`1080x1920`). Each size is a paid model render: don't add sizes nobody asked for.

### 2. Resize

```bash
python3 scripts/resize_image.py --file banner.png \
  --size "1080x1920=Instagram Story" --size "1200x627=LinkedIn"
```

(or `--url <public image>`; max 50 MB.) Returns `outputs`: one entry per size
with `label`, `dimension` and `image_url`. Some sizes can fail while others
render: report the ones that worked and name the ones that didn't; the script
only fails if every size fails.

`--tier PRO` plans each size first and waits for approval: the script stops
with `status: needs_approval` and `awaiting_approval` (the sizes). Ask the user,
then approve here (below). The default (`FLASH`) renders straight away.

Keep `asset` from the result for the commands below; never show it.

### 3. Check, fix, save (only if asked)

```bash
python3 scripts/sizes.py list --asset <asset>                          # each size and its image
python3 scripts/sizes.py approve --asset <asset> --size Story           # PRO: ⏸ after the user agrees
python3 scripts/sizes.py redo --asset <asset> --size Story [--note "keep the logo top left"]   # ⏸ paid
python3 scripts/sizes.py review --asset <asset> --size Story            # ⏸ paid check: numbered issues
python3 scripts/sizes.py fix --asset <asset> --size Story --issues 1,3|all    # ⏸ paid
python3 scripts/sizes.py versions --asset <asset> --size Story / restore … --version 2
python3 scripts/sizes.py save --asset <asset> --size Story [--folder "Q3 creatives"]   # into the Drive
python3 scripts/sizes.py export --asset <asset> [--size Story …] [--format jpeg] [--out-dir ./out]
python3 scripts/sizes.py rename --asset <asset> --name "Diwali banner" / move … --folder "Diwali"
python3 scripts/sizes.py assets                                          # past resized images
```

Sizes are named by label or `WxH`; issues by number, with what was found and
the suggested fix. Relay them as before → after and let the user pick.

## Rules

- **Never show ids.** Give each label with its link.
- **Exact pixels only** (`1080x1920`). To reshape an image this organization
  translated by aspect ratio, use image-translation's `resize_translated.py`.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow uploads and adaptive resize for their role |
| 4 | Bad `--size`, API error, or every size failed | `--size` is `WIDTHxHEIGHT`; otherwise the message |
| 5 | Timed out | Still rendering: run again, or raise `--max-wait` for many sizes |
| 6 | Image unreadable or too large | Ask for a file under 50 MB or a reachable URL |
