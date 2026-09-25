# Voices and translation memories

## Voices (step 3)

Speakers are detected per video. The API does not know a speaker from an
earlier dub; the organization's saved cloned voices come back in
`saved_cloned_voices` so a returning speaker can keep theirs.

Ask once, for every speaker and every target language:

| Choice | `--voice-map` value | When |
|---|---|---|
| Their own voice | `clone` | Default. A fresh instant clone of that speaker. |
| A saved voice | the voice's `voice_id` | The user names one from `saved_cloned_voices`. Match by id, never by a similar name. |
| Leave as detected | `keep` | Rare: keep whatever the gate already assigned. |

`--voice-map` is JSON keyed by speaker id; `"*"` covers every target language:

```json
{ "1": { "*": "clone" }, "2": { "hindi_india": "<voice_id>" } }
```

Speakers or languages left out follow `--voice-mode`: `clone` (default) or
`library_auto` (keep the library voice the gate picked). If a chosen voice
can't speak a target language (`supported_languages`), ask; never substitute.

The answer is saved in the run record: re-running `resume_dub.py` and
`add_language.py` reuse it, so the user is asked once. Later changes for one
speaker in one language: `card_ops.py speaker-voice` (see [editing](editing.md)).

## Translation memories (step 1)

A memory holds the organization's approved wording, so names, tone and terms
come out the same in every job.

```bash
python3 scripts/list_tms.py --source-language english_united_states --target-language hindi_india
```

- **Several:** ask which, by name; offer "none". Pass the name to
  `dub_video.py --tm-name`.
- **One:** use it and say so in one line.
- **None:** omit `--tm-name`. The server finds or creates the memory named
  `dub · <source> → <targets>` for this language pair, so later dubs of the same
  pair share it.

`list_tms.py` filters by the **target** language. VitraTM memories accept any
source language, so a memory listed with a different source still works.

### Provider and engine

```bash
python3 scripts/list_providers.py
```

Only offer a choice when there is one: if one provider is listed (usually
VitraTM), use it silently. Providers printed as `[unavailable]` are not
connected for this organization; never offer them.

A VitraTM memory translates what it doesn't already know with an **engine**:
`gemini` (the default; follows the memory's style guide) or `azure` (Microsoft
Translator; ignores the style guide). The engine belongs to the memory and is
changed in Vitra's memory settings, not per dub.
