# Editing a dub

Always read first: `inspect_process.py --cards <lang>` lists the lines,
numbered as the user sees them (`line`), with text, timing, emotion, audio and
the current `revision`. Show the user the proposed change, then apply it with
that `--revision` (leave it out if it is null). Refer to lines by number, never
by anything else. Every command reports each change as `before → after`: relay
them all. After a split, merge, add or delete (`renumbered: true`), read the
lines again before the next change.

## Change lines: `patch_cards.py`

```bash
python3 scripts/patch_cards.py --job-id <job> --language <lang> --revision <rev> \
  --edits '[{"line":3,"text":"...","emotion":"calm"},
            {"line":4,"start":12.4,"end":15.1},
            {"line":5,"rate":1.1},
            {"line":6,"review_status":"a"}]'
```

| Field | Values | What happens to the audio |
|---|---|---|
| `text` | new line | **Removed** (it spoke the old line): listed in `audio_cleared` → `regenerate_cards.py --missing` |
| `emotion` | `neutral happy excited calm sad angry frustrated anxious surprised playful confident hesitant tired mysterious affectionate sarcastic curious disappointed confused` | Kept but out of date: listed in `audio_stale` → `regenerate_cards.py --stale` |
| `start`, `end` | seconds, inside the video, not overlapping neighbours | Kept |
| `rate` | 0.5–2.0 | Kept. The server may pick the nearest workable rate: then `adjusted_by_server` is true |
| `keep_source` | true/false | Plays the original recording for that line. A deliberate exception, never a fix for missing audio |
| `lip_sync` | true/false | Kept |
| `review_status` | `u` unverified, `v` verified, `a` approved | Kept |
| `volume` | 0–1 | Kept |

Everything is validated before anything is sent: one bad edit changes nothing.
The source language accepts `text` and timing only; `affected_languages` then
lists languages translated from the old text (re-translate those lines).

`--dry-run` shows the before → after without saving.

## Restructure lines: `card_ops.py`

| Operation | Command | Leaves to do |
|---|---|---|
| Split a line (2–3 parts, the source words unchanged) | `split --line N --chunks '["part 1","part 2"]'` | New lines have no translation or audio: `retranslate`, then `speak` or `regenerate_cards --missing` |
| Merge consecutive lines of one speaker | `merge --lines N,M` | Merged line needs audio: `regenerate_cards --missing` |
| Add a line in the silence next to line N | `add --after N --start S --end E --text "..."` (or `--before N`) | Empty in every dubbed language: `retranslate`, then `speak` |
| Delete a line | `delete --line N` | — |
| Move a line to another speaker | `assign-speaker --line N --speaker-id S` | Re-voice it: `speak` |
| New speaker for a line | `add-speaker --line N --label "Name" --gender male\|female` | Give them a voice: `speaker-voice` |
| One speaker's voice in one language | `speaker-voice --speaker-id S --language L --voice-id V --voice-name "..."` | That speaker's lines lose audio: `regenerate_cards --missing` |
| Re-translate one line from the source | `retranslate --line N --language L` | Then `speak` |
| Re-voice one line now (optionally another voice) | `speak --line N --language L [--voice-id V --voice-name "..."]` | — |

`retranslate` and `speak` spend credits and run immediately; ask first. Their
`follow_up` field says what the change left to do.

## Subtitle lines: `edit_subtitles.py`

A dub's subtitles are their own numbered lines per language: list them with
`inspect_process.py --job-id <job> --subtitles <lang>`, then

```bash
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> \
  --edits '[{"line":3,"text":"New text\nsecond row"},{"line":4,"start":12.5,"end":14}]'
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> --split 3 --at-word 6
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> --merge 3,4
python3 scripts/edit_subtitles.py --job-id <job> --language <lang> --delete 3
```

## Regenerate speech: `regenerate_cards.py`

`--missing` (lines without audio), `--stale` (lines whose emotion changed) or
`--lines 3,7`. Only those lines are re-voiced. It confirms each line's new
audio by comparing the file itself (`audio_changed`, `verified`).

## Repair blocking issues: `fix_issues.py`

The editor's "Fix all issues", bounded by `--budget` (default 1 attempt). Lines
with only missing audio are re-voiced; rate problems go through autofix, which
may shorten a translation to fit its time slot. Relay every change it reports,
and call out `approved_text_changed` (text the user had approved). Timing or
content errors it can't fix stay in `remaining_errors` for `patch_cards` or
`card_ops`.

## Pronunciation: `pronunciations.py`

When a voice says a word wrong (a brand, an acronym, a name), set how it
should sound, for the whole organization or just one line:

```bash
python3 scripts/pronunciations.py list --language hindi_india
python3 scripts/pronunciations.py add --word SQL --say sequel --language hindi_india
python3 scripts/pronunciations.py add --word Acme --say "ˈæk.mi" --phoneme --language english_united_states
python3 scripts/pronunciations.py add --word Priya --say Pree-ya --language english_united_states --job-id <job> --line 12
python3 scripts/pronunciations.py remove --word SQL --language hindi_india
```

A rule changes new speech only: re-voice the lines that use the word
(`regenerate_cards.py --lines …`) for it to be heard. An organization rule
applies to every future dub in that language: confirm before adding one.

## Typing another script: `transliterate.py`

When the user types a correction in Latin letters for a language written in
another script ("namaste dosto" for Hindi), convert it before saving:

```bash
python3 scripts/transliterate.py --language hindi_india --text "namaste dosto"
```

Show `text` (and any `alternatives`) and let the user confirm, then save it
with `patch_cards.py`.

