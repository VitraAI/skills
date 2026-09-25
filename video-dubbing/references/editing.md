# Editing a dub

Always read first (`inspect_process.py --cards <lang>` gives each line's
`card_id`, text, timing, emotion, audio and the current `revision`), show the
user the proposed change, then apply it with that `--revision`. Every command
reports each change as `before → after`: relay them all.

## Change lines: `patch_cards.py`

```bash
python3 scripts/patch_cards.py --job-id <job> --language <lang> --revision <rev> \
  --edits '[{"card_id":"<id>","text":"...","emotion":"calm"},
            {"card_id":"<id2>","start":12.4,"end":15.1},
            {"card_id":"<id3>","rate":1.1},
            {"card_id":"<id4>","review_status":"a"}]'
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
| Split a line (2–3 parts, the source words unchanged) | `split --card-id <id> --chunks '["part 1","part 2"]'` | New lines have no translation or audio: `retranslate`, then `speak` or `regenerate_cards --missing` |
| Merge consecutive lines of one speaker | `merge --card-ids <a>,<b>` | Merged line needs audio: `regenerate_cards --missing` |
| Add a line in a gap | `add --after <id> --start S --end E --text "..."` | Empty in every dubbed language: `retranslate`, then `speak` |
| Delete a line | `delete --card-id <id>` | — |
| Move a line to another speaker | `assign-speaker --card-id <id> --speaker-id N` | Re-voice it: `speak` |
| New speaker for a line | `add-speaker --card-id <id> --label "Name" --gender male\|female` | Give them a voice: `speaker-voice` |
| One speaker's voice in one language | `speaker-voice --speaker-id N --language L --voice-id V --voice-name "..."` | That speaker's lines lose audio: `regenerate_cards --missing` |
| Re-translate one line from the source | `retranslate --card-id <id> --language L` | Then `speak` |
| Re-voice one line now (optionally another voice) | `speak --card-id <id> --language L [--voice-id V --voice-name "..."]` | — |
| Subtitle lines | `sub-update`, `sub-delete`, `sub-split --at-word N`, `sub-merge --subtitle-ids a,b` | — |

`retranslate` and `speak` spend credits and run immediately; ask first. Their
`follow_up` field says what the change left to do.

## Regenerate speech: `regenerate_cards.py`

`--missing` (lines without audio), `--stale` (lines whose emotion changed) or
`--card-ids a,b`. Only those lines are re-voiced. It confirms each line's new
audio by comparing the file itself (`audio_changed`, `verified`).

## Repair blocking issues: `fix_issues.py`

The editor's "Fix all issues", bounded by `--budget` (default 1 attempt). Lines
with only missing audio are re-voiced; rate problems go through autofix, which
may shorten a translation to fit its time slot. Relay every change it reports,
and call out `approved_text_changed` (text the user had approved). Timing or
content errors it can't fix stay in `remaining_errors` for `patch_cards` or
`card_ops`.
