---
name: image-translation
description: >-
  Translates the text baked into an image — signage, packaging, ad creatives,
  screenshots, menus — using the Vitra Universe Image Translator API, and
  re-renders it in the target language with the original layout preserved. Use
  for "translate this poster into French", "what does this sign say, and make me
  a Spanish version", "localize this ad creative". Input is a local image file OR
  a public image URL, plus a target language. Do NOT use for generating a new
  image from a prompt, for resizing to other aspect ratios, or for translating a
  document/subtitle file — those are the image-creator, image-resize and
  document skills.
compatibility: >-
  Python 3, standard library only. Outbound HTTPS. One env var:
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization). The key is bound
  to one organization and acts with its creator's role there — that member needs
  translate_photo.image_translator create/read.
metadata:
  skill-author: Vitra.ai
  version: "1.1"
  display-name: Image Translation
  category: Localization
  tags: Image, Translation
  source: vitra
  added: "2026-09-10"
  updated: "2026-09-25"
---

# image-translation

Translates the text inside an image and re-renders it in place.

**`translate_image.py`** does the whole job in one call — it mirrors the four
steps the webapp performs:

1. `analyze` — upload the image; the API finds the text regions.
2. poll until analysis is done.
3. `translate` — translate into the target language.
4. poll until the re-rendered image exists → `translatedImageUrl`.

**`resize_translated.py`** is the follow-up: re-render a translated image at a
different aspect ratio, reusing the translation already done.

## Critical

- **One env var:** `VITRA_UNIVERSE_API_KEY` — a `uvk_` key for one Vitra
  organization. If it is missing, stop and show the caller BOTH
  setup options (see "When the key is missing"). Never echo the key.
- **The organization comes from the key.** Never ask the caller which org.
- **ALWAYS ask which Translation Memory to use when more than one covers the
  language pair.** Run `list_tms.py` first and put the choice to the caller —
  never pick silently. Picking wrong writes the wrong wording into a memory the
  whole organization reuses, and that is not visibly undone later.
- **Never show the caller a job id or version id.** They are plumbing — report
  the finished image URL.
- **Max 10MB** per image. A larger file exits 6; ask for a smaller one rather
  than retrying.
- **This is not OCR-then-translate-text.** The output is a new *image* with the
  translated text set back into the original layout. If the caller only wants to
  know what the text says, tell them the skill returns a rendered image.

## Usage

```bash
python3 scripts/translate_image.py --file poster.png --target-language French
python3 scripts/translate_image.py --url "https://example.com/sign.jpg" --target-language "Hindi"
```

Prints `{"status":"completed","image_url":"…","target_language":"French"}`.
Give the caller the `image_url`.

Options:

- `--source-language` — defaults to `auto` (detected). Pass it when the caller
  states the source language, or when auto-detection guessed wrong.
- `--tm-name` — a Translation Memory to reuse, by the name `list_tms.py` shows.
  See "Translation Memory" below.
- `--max-wait` — seconds before giving up (default 600).

## Translation Memory — ask, don't guess

A TM holds the organization's approved wording. Reusing one keeps product names,
tone and terminology identical to what they've translated before; without one,
every run is translated fresh and the same phrase can come out differently.

So **before translating, check what's available for that language pair**:

```bash
python3 scripts/list_tms.py --source-language English --target-language French
```

Then act on what came back:

- **Several listed → ASK.** Show the caller the TM names and let them pick.
  Offer "none" and "make a new one" as real options too. Pass their choice,
  exactly as listed, as `--tm-name`. Do not pick for them: two TMs for one pair usually
  means different clients or products, and choosing wrong silently contaminates
  a memory with the wrong wording.

  > I found two translation memories for English → French:
  > **Acme Marketing** and **Acme Legal**. Which should I use — or neither?

- **Exactly one → use it, and say so** in one line. Don't make anyone choose
  from a list of one.

  > Using the **Acme Marketing** translation memory.

- **None listed → create one**, so the next run for this pair is consistent
  with this one:

  ```bash
  python3 scripts/translate_image.py --file poster.png \
    --source-language English --target-language French --create-tm
  ```

  `--create-tm` finds-or-creates a TM named `image · <source> → <target>`, so
  repeated runs of the same pair share one memory instead of spawning
  duplicates. It never fails the run: if creation doesn't work, the translation
  proceeds without a TM.

Never invent a `--tm-name`. `list_tms.py` already filters to TMs that can serve
the request, so anything it lists is safe to offer. Its lines carry no ids, and
nothing you show the caller should either.

Note it filters on the **target** language, not the source: VitraTM memories are
multi-source, so a TM created for one source language still serves another.
That is why a TM whose listed source differs from this run can still appear —
it is not a bug, and it is fine to use.

### Which provider?

Only ask when there is a real choice. Check first:

```bash
python3 scripts/list_providers.py
```

- **One line on stdout** (the usual case — only VitraTM) → **don't ask.** Use
  it silently. Offering a choice of one wastes the caller's time.
- **Two or more** → ask, in the same breath as the TM question:

  > This organization has both **VitraTM** and **Phrase** connected. Which
  > should I use for this translation?

Pass the answer as `--tm-provider`. Anything the script printed to *stderr* is
NOT connected for this org — never offer it, and never suggest they "switch to
Phrase" as a fix.

The two differ in one way that matters here: **VitraTM memories are
multi-source** (one memory serves any source language), **Phrase memories are
tied to their source language**.

## Resizing after a translation

When the caller wants the translated image in another shape ("also give me a
portrait version", "make it square for Instagram"), use the `job_id` from
`translate_image.py`:

```bash
python3 scripts/resize_translated.py --job-id "<job_id>" --aspect-ratio 9:16
```

Synchronous, and it returns a new version each time — so several ratios means
several calls against the same `job_id`. Take **ratios** (`9:16`, `1:1`, `16:9`),
not pixel sizes; map a platform name to its ratio yourself.

Use this only for an image this skill already translated. To resize an arbitrary
image at exact pixel dimensions, that is the **image-resize** skill.

## Asking the caller

Only one thing is genuinely required: **the target language.** Ask for it if it
isn't in the request. Everything else has a sane default — don't interrogate.

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
| 3 | Key rejected or lacks permission | Needs `translate_photo.image_translator` create/read. |
| 4 | API error, or no text found in the image | Report the message. If no text was detected, say so — the image may have no readable text. |
| 5 | Timed out | Re-run; a very dense image can exceed the default wait. |
| 6 | Source unreadable / too large | Ask for a file under 10MB or a reachable URL. |
