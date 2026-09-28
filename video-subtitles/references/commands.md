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
| `start_subtitles` | `--file` \| `--url` (a video), `--source-language`, `--script`, `--tm-name` \| `--create-tm --target-language <key> --tm-context "..." [--tm-engine gemini\|azure]`, `--name` | `review_ready` with `memory`, `progress`; or a question: `TM_CHOICE_NEEDED`, `TM_NEEDED`, `TM_CONTEXT_NEEDED`. A subtitle file is refused (`WRONG_SKILL`): that's subtitle-translation |
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
