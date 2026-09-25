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
| `list_languages` | — | One line per language: `<key>  <label>` |
| `list_tms` | `--source-language`, `--target-language` | Memories that fit: name, languages, provider, engine |
| `list_providers` | — | Connected providers; `[unavailable]` ones must not be offered |
| `list_assets` | `--file` \| `--sha256` \| `--name` | Earlier uploads of the same video and the dubs made from them |

## Making the dub

| Script | Options | Returns |
|---|---|---|
| `dub_video` | `--file` \| `--url`, `--source-language`, `--target-language` (repeatable), `--tm-name`, `--name`, `--no-emotion-detection`, `--new-run` | `awaiting_voices` + `speakers`, `saved_cloned_voices`; or `review_ready` when it reconnected to a dub past that point |
| `resume_dub` | `--job-id`, `--voice-map`, `--voice-mode clone\|library_auto` | `review_ready` or `failed` |
| `add_language` | `--job-id`, `--language`, `--voice-map`, `--expected-revision` | `review_ready`, `exists`, `failed`; `VOICE_DECISION_NEEDED` error when a speaker has no voice |

## Review and repair

| Script | Options | Returns |
|---|---|---|
| `inspect_process` | `--job-id`, `--cards <lang>` | `progress` (the webapp's steps), `revision`, per-language `cards` and `issues`, `suggestions`; with `--cards`, every line |
| `get_card_media` | `--job-id`, `--card-id`, `--language`, `--download DIR` | The source segment and the line's audio |
| `list_issues` | `--job-id`, `--language` | `clean` or `blocked`, with `errors` and `warnings` |
| `fix_issues` | `--job-id`, `--language`, `--budget` | `clean`, `partial` or `failed`; every change made |
| `patch_cards` | `--job-id`, `--language`, `--edits`, `--revision`, `--dry-run` | `changes`, `audio_cleared`, `audio_stale`, `affected_languages`, `revision_after` |
| `card_ops` | an operation + its options (see [editing](editing.md)) | `cards`, `follow_up`, `revision_after` |
| `regenerate_cards` | `--job-id`, `--language`, `--missing` \| `--stale` \| `--card-ids` | Per line: `has_audio`, `audio_changed`, `verified` |

## Delivery

| Script | Options | Returns |
|---|---|---|
| `export_dub` | `--job-id`, `--language`, `--revision`, `--resolution 4K\|2K\|1080\|720\|480\|360`, `--lip-sync` | `exported` + `export_id`, or `refused` + `reason` |
| `download_export` | `--export-id`, `--out`, `--job-id` | `downloaded`, `path`, `sha256`, `media_check` |

## Recovery

| Script | Options | Returns |
|---|---|---|
| `retry_dub` | `--job-id` | Resumes a failed dub at the failed step: `awaiting_voices`, `review_ready` or `failed` |
| `run_manifest` | `list` \| `show` \| `validate` \| `forget`, `--job-id` | This machine's record of each dub: what was chosen, exported, and what changed since |

Scripts wait for their own jobs with backoff and never start a job twice:
re-running the same command after a timeout or a dropped connection picks up
where it stopped.
