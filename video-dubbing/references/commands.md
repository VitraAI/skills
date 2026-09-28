# Commands

Every script is run as `python3 scripts/<name>.py` and prints one JSON line on
stdout (progress goes to stderr). On failure the line is
`{"status": "failed", "error": {"code", "message", "retryable"}, "request_id"}`.

## Contents
- Setup and lookups
- Making the dub
- Review and repair
- Delivery
- Recovery

## Setup and lookups

| Script | Options | Returns |
|---|---|---|
| `check_access` | — | `status`: ready / partial / blocked / unknown; `can`, `cannot` |
| `list_languages` | `<name> [...]` | `<key>  <label>` per match (search by name, key or code) |
| `list_tms` | `--source-language`, `--target-language` | Memories that fit: name, languages, provider, engine |
| `list_providers` | — | Connected providers; `[unavailable]` ones must not be offered |
| `list_assets` | `--file` \| `--sha256` \| `--name` | Earlier uploads of the same video and the dubs made from them |

## Making the dub

| Script | Options | Returns |
|---|---|---|
| `dub_video` | `--file` \| `--url`, `--source-language`, `--target-language` (repeatable), `--script`, `--tm-name`, `--name`, `--no-emotion-detection`, `--new-run` | `awaiting_voices` + `speakers`, `saved_cloned_voices`; or `review_ready` when it reconnected to a dub past that point |
| `resume_dub` | `--job-id`, `--voice-map`, `--voice-mode clone\|library_auto` | `review_ready` or `failed` |
| `add_language` | `--job-id`, `--language`, `--voice-map`, `--expected-revision` | `review_ready`, `exists`, `failed`; `VOICE_DECISION_NEEDED` error when a speaker has no voice |

## Review and repair

| Script | Options | Returns |
|---|---|---|
| `inspect_process` | `--job-id`, `--cards <lang>`, `--subtitles <lang>`, `--offset`, `--limit` | `progress` (the webapp's steps), `revision`, per-language `cards` and `issues`, `suggestions`; with `--cards`, numbered `lines`; with `--subtitles`, numbered `subtitle_lines` |
| `get_card_media` | `--job-id`, `--line`, `--language`, `--download DIR` | The source segment and the line's audio |
| `list_issues` | `--job-id`, `--language` | `clean` or `blocked`, with `errors` and `warnings` (each names its `line`) |
| `fix_issues` | `--job-id`, `--language`, `--budget` | `clean`, `partial` or `failed`; every change made |
| `patch_cards` | `--job-id`, `--language`, `--edits` (by `line`), `--revision`, `--dry-run` | `changes`, `audio_cleared`, `audio_stale` (line numbers), `affected_languages`, `revision_after` |
| `card_ops` | an operation + its options (see [editing](editing.md)) | `lines`, `renumbered`, `follow_up`, `revision_after` |
| `edit_subtitles` | `--job-id`, `--language`, `--edits` \| `--split N --at-word W` \| `--merge N,M` \| `--delete N`, `--revision` | `changes`, `renumbered`, `revision_after` |
| `regenerate_cards` | `--job-id`, `--language`, `--missing` \| `--stale` \| `--lines 3,7` | `lines`: per line `has_audio`, `audio_changed`, `verified` |

## Pronunciation and scripts

| Script | Options | Returns |
|---|---|---|
| `pronunciations` | `list` \| `add` \| `remove`, `--word`, `--say`, `--language`, `--phoneme`, `--job-id --line` | `rules`, or `added` / `removed` with `next_action: regenerate_cards` |
| `transliterate` | `--text`, `--language` | `text` in the language's script, `alternatives` per word |

## Delivery

| Script | Options | Returns |
|---|---|---|
| `export_dub` | `--job-id`, `--language`, `--revision`, `--resolution 4K\|2K\|1080\|720\|480\|360`, `--lip-sync`, `--subtitles <lang>`, `--generate-subtitles` | `exported` + `export_id`, or `refused` + `reason` (`no_subtitles`: that language has no subtitle lines yet) |
| `download_export` | `--export-id`, `--out`, `--job-id` | `downloaded`, `path`, `sha256`, `media_check` |

## Recovery

| Script | Options | Returns |
|---|---|---|
| `retry_dub` | `--job-id` | Resumes a failed dub at the failed step: `awaiting_voices`, `review_ready` or `failed` |
| `run_manifest` | `list` \| `show` \| `validate` \| `forget`, `--job-id` | This machine's record of each dub: what was chosen, exported, and what changed since |

## Job controls (`job_tools.py`)

| Action | Options | Does |
|---|---|---|
| `cancel` | `--job-id`, `--confirm` | Stops a running job (asks first) |
| `cancel-export` | `--job-id` | Stops an export in progress |
| `sync` | `--job-id`, `--to-memory` \| `--from-memory` | Saves checked lines to the memory, or refreshes lines from it |
| `emotion` | `--job-id`, `--language`, `--emotion`, `[--lines 1,4\|all]` | Sets the delivery (calm, happy…) for voiced lines; regenerate after |
| `settings` | `--job-id`, `[--background-volume 0-1]`, `[--break-subtitles yes\|no]` | Shows or changes the video settings |
| `sheet` | `--job-id`, `--type transcript\|subtitle`, `[--language]`, `--out x.csv` | Every line as a spreadsheet (opens in Excel) |
| `save` | `--export-id` | Puts a finished export in the Drive |
| `move` | `--job-id`, `--folder NAME\|Unassigned` | Files the job in a work folder |

Scripts wait for their own jobs with backoff and never start a job twice:
re-running the same command after a timeout or a dropped connection picks up
where it stopped.
