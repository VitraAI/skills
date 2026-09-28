---
name: image-translation
description: >-
  Translates the text inside an image — signage, packaging, ad creatives,
  screenshots, menus, infographics — with the Vitra Universe Image Translator,
  and re-renders the image in the target language with the original layout
  kept; it can then re-render the translated image in other aspect ratios. Use it
  whenever the user wants an image, poster, banner or creative localized or its
  text translated — "translate this poster into French", "make a Spanish version
  of this ad", "localize these product images" — even if they only say "translate
  this". Not for generating new images (image-creator), resizing an untranslated
  image (image-resize), or translating documents or subtitles.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs a
  Vitra sign-in (scripts/login.py opens the browser) or VITRA_UNIVERSE_API_KEY
  (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Image Translation
  category: Localization
  tags: Image, Translation
  source: vitra
  added: "2026-09-10"
  updated: "2026-09-28"
---

# Image Translation

Finds the text in an image, translates it and sets it back in place, as a new
image. Every script prints one line of JSON and waits for its own job (up to 10
minutes by default): don't poll and don't re-run a slow call.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: continue without the steps in `cannot`.
`blocked`: stop and tell the user which steps their key can't do; their Vitra
admin can grant them. Key missing (exit 2): relay the setup lines it prints.

## Collect the inputs

| Input | Required | How |
|---|---|---|
| The image | yes | A local file (max 10 MB) or a public http(s) URL |
| Target language | yes | Ask if it isn't in the request, e.g. `French` |
| Source language | no | Auto-detected; pass `--source-language` only if the user says it or detection was wrong |

## The flow

```
- [ ] 1. Pick a translation memory   (⏸ ask if several)
- [ ] 2. Translate                   → show the image
- [ ] 3. More languages              (only if asked, or several were asked for)
- [ ] 4. Other shapes                (only if asked)
- [ ] 5. Correct the text            (only if asked)
- [ ] 6. Save, file, find again      (only if asked)
```

### 1. Translation memory

```bash
python3 scripts/list_tms.py --source-language English --target-language French
```

⏸ **Several:** ask which, by name, and offer "none"; the wrong one writes the
wrong wording into a memory the whole organization reuses. **One:** use it and
say so. **None:** ask whether to create one; if yes, ⏸ ask one sentence on who it
is for (the client or product, and the audience) — the server requires it and
uses it for every translation through that memory.

`list_tms.py` filters by target language; VitraTM memories accept any source,
so one listed with a different source still works. Only offer a provider choice
if `list_providers.py` lists more than one; a VitraTM memory's engine is
`gemini` (default, follows the style guide) or `azure` (ignores it).

### 2. Translate

```bash
python3 scripts/translate_image.py --file poster.png --target-language French \
  [--tm-name "<memory>"]
```

or, to create the memory for this language pair:

```bash
python3 scripts/translate_image.py --file poster.png --target-language French \
  --create-tm --tm-context "Acme's retail posters for shoppers in France" [--tm-engine gemini]
```

Returns `image_url` (show it), `memory` (the memory used, or none) and `job_id`
(keep it for steps 3 and 4; never show it). If it stops with `TM_CONTEXT_NEEDED`, ask the question in
`error.ask` and run again with `--tm-context`.

### 3. More languages

Asked for several languages? Translate the first as in step 2, then add the
rest to the same image in one command:

```bash
python3 scripts/add_language.py --job-id <job_id> --target-language German --target-language Spanish
```

The image is analysed once, so each extra language costs only its translation.
A language the image already has comes back as is (`reused: true`); add
`--again` only if the user wants it redone. Show each `image_url` with its
language.

### 4. Other aspect ratios (only if asked)

```bash
python3 scripts/resize_translated.py --job-id <job_id> --aspect-ratio 9:16
```

Reuses the translation already done: one call per ratio (`9:16`, `1:1`, `16:9`).
Map a platform to its ratio yourself ("Instagram story" → `9:16`). For exact
pixel sizes, or an image that wasn't translated here, use image-resize.

### 5. Correct the text (only if asked, or the user spots a mistake)

```bash
python3 scripts/edit_text.py --job-id <job_id> [--language French]          # the lines, numbered
python3 scripts/edit_text.py --job-id <job_id> --set "3=Promo" [--keep 5]   # ⏸ re-renders
python3 scripts/edit_text.py --job-id <job_id> --verify all [--sync-to-memory]
```

Show the lines as `before → after` by number. `--set` changes a line and
re-renders the image as a new version (only unchanged lines are translated
again); `--keep` leaves a line in the original language (brand names).
`--verify` marks lines checked; `--sync-to-memory` saves them to the memory.

### 6. Save, file, find again

```bash
python3 scripts/save_to_drive.py --job-id <job_id> [--language French] [--folder "Q3 creatives"] [--name …]
python3 scripts/images.py list [--search poster] [--language French]    # past images, newest first
python3 scripts/images.py move --job-id <job_id> --folder "Diwali"        # work folder, or Unassigned
python3 scripts/images.py retry --job-id <job_id>                         # redo what failed
python3 scripts/images.py template --job-id <job_id> --language French    # campaign images only
```

`images.py list` gives each image's `job_id` for these commands; show the
name and languages, never the id.

## Rules

- **Never show ids.** Show the image link, the language, and the memory used.
- **The result is an image, not text.** If the user only wants to know what the
  text says, tell them this returns a translated image.
- **Never invent a memory name.** Offer only what `list_tms.py` printed.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow image translation for their role |
| 4 | API error, or no text found | The message; if no text was found, the image may have no readable text |
| 5 | Timed out | It's still working: run the same command again |
| 6 | Image unreadable or too large | Ask for a file under 10 MB or a reachable URL |
