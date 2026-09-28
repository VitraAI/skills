---
name: content-compliance
description: >-
  Checks content against each market's rules before it goes out, with the
  Vitra Universe API: text, images, audio and video are scored per market
  (APPROVED, REVIEW or BLOCKED) with the rules they break, explained, plus
  unsafe-content detection; a flagged image can be regenerated to meet a
  market's rules. Use it whenever the user asks if content is okay for a
  market or audience — "is this ad OK for Saudi Arabia?", "check this video
  for our India rules", "will this banner pass compliance in Germany?", "fix
  this image for the UAE". Not for translation quality (translation-quality).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs a
  Vitra sign-in (scripts/login.py opens the browser) or VITRA_UNIVERSE_API_KEY
  (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Content Compliance
  category: Quality
  tags: Compliance, Image, Video
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Content Compliance

Scores content against the rules of the markets the organization defined,
and fixes flagged images. Each script prints **one line of JSON** and waits
for its own job.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: don't offer the steps in `cannot`.
`blocked`: stop and tell the user which steps their key can't do.

## The flow

```
- [ ] 1. Markets   (⏸ which ones, if not named)
- [ ] 2. Check     (⏸ confirm: spends credits) → verdict per market
- [ ] 3. Fix       (images only, if flagged and the user wants it)
```

### 1. Markets ⏸

```bash
python3 scripts/list_markets.py
```

Use the names exactly. If the user names a market that isn't there, say so;
the organization's admin adds markets and their rules in Vitra.

### 2. Check ⏸

```bash
python3 scripts/check_content.py --text "Our summer sale…" --market "Saudi Arabia" [--market "India"]
python3 scripts/check_content.py --file banner.png --market Germany
python3 scripts/check_content.py --file ad.mp4 --market UAE [--scope video|audio|both]
```

Files: images (up to 32 MB), audio (128 MB), video (512 MB). Report the
overall `verdict`, then per market its `verdict`, `score` and `concerns`:
`fails` first (with `why`), then `caution`. Mention `unsafe` findings.

### 3. Fix an image ⏸

When `fixable` is true and the user wants it:

```bash
python3 scripts/fix_image.py --check <check> --market "Saudi Arabia" --out banner.sa.png \
  [--concern "<title>"] [--instructions "keep the logo unchanged"]
```

Spends credits. Show the new image and `changes`, then offer to check it again.

## Rules

- **Explain concerns in plain words**, worst first; don't dump every rule.
- **A verdict is advice, not legal sign-off.** `REVIEW` means a person should look.
- **Ask before spending credits.** Show names, never ids.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.
`MARKET_UNKNOWN`: use a name `list_markets.py` printed.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow quality control for their role |
| 4 | API error, or an unsupported file | Explain the message |
| 5 | Timed out | Still checking: try again later |
| 6 | File not found | Ask for the right path |
