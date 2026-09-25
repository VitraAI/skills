# Commands

Every script is run as `python3 scripts/<name>.py` and prints one JSON line on
stdout (progress goes to stderr). On failure the line is
`{"status": "failed", "error": {"code", "message", "retryable"}, "request_id"}`;
a question for the user comes as `error.ask` (and `choices` when there are
options).

## Setup and lookups

| Script | Options | Returns |
|---|---|---|
| `check_access` | — | `status`: ready / partial / blocked / unknown; `can`, `cannot` |
| `list_languages` | `<name> [...]` | `<key>  <label>` per match (search by name, key or code) |
| `list_tms` | `--source-language`, `--target-language` | Memories that fit: name, languages, provider, engine |
| `list_providers` | — | Connected providers; `[unavailable]` ones must not be offered |

## Making subtitles

| Script | Options | Returns |
|---|---|---|
| `start_subtitles` | `--file` \| `--url`, `--source-language`, `--target-language` (repeatable; subtitle files), `--script` (videos), `--tm-name` \| `--create-tm --tm-context "..." [--tm-engine gemini\|azure]`, `--name` | `review_ready` with `mode` (generate / translate), `memory`, `progress`; or a question: `TM_CHOICE_NEEDED`, `TM_NEEDED`, `TM_CONTEXT_NEEDED`, `TARGET_LANGUAGE_NEEDED` |
| `add_subtitle_language` | `--job-id`, `--language` (repeatable), `--expected-revision` | `review_ready`, `partial` or `failed`; `added`, `failed` |
| `retry_subtitles` | `--job-id` | Resumes a failed job at the failed step: `review_ready` or `failed` |

## Review

| Script | Options | Returns |
|---|---|---|
| `inspect_subtitles` | `--job-id`, `--lines <lang>`, `--offset`, `--limit` | `progress`, `revision`, `languages` (line counts), `suggestions`; with `--lines`, numbered `lines`, `lines_total`, `more` |
| `edit_subtitles` | `--job-id`, `--language`, `--revision`, one of `--edits '[{"line":N,"text"?,"start"?,"end"?}]'`, `--split N --at-word W`, `--merge N,M`, `--delete N` | `changes` (before → after), `renumbered`, `revision_after` |

## Delivery

| Script | Options | Returns |
|---|---|---|
| `download_subtitles` | `--job-id`, `--language`, `--format srt\|vtt\|dfxp\|xml\|stl\|edl\|txt\|txt-timed\|json`, `--out` | `downloaded`, `path`, `lines`, `bytes` |
| `burn_subtitles` | `--job-id`, `--language`, `--resolution 4K\|2K\|1080\|720\|480\|360` | `exported` + `export_id`, `media_url` |
| `download_export` | `--export-id`, `--out`, `--job-id` | `downloaded`, `path`, `sha256`, `media_check` |

Scripts wait for their own jobs with backoff and never start a job twice:
re-running the same command after a timeout or a dropped connection picks up
where it stopped.
