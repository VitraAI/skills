# Troubleshooting — video-dubbing

## Exit codes

Every script exits with one of these. Map the code to a message for the caller
in plain terms — **do not paste ids, UUIDs, or raw stderr to the caller.**

| Exit | Meaning                     | What to tell the caller                                             |
| ---- | -------------------------- | ------------------------------------------------------------------ |
| 0    | Success                     | —                                                                  |
| 2    | API key not set             | "The Vitra API key isn't configured." Show `export VITRA_UNIVERSE_API_KEY=<uvk_...>`. |
| 3    | Auth rejected (401 / 403)   | The key is wrong or expired, or its creator lacks translate-video / translation-memory permission in the org the key is bound to. |
| 4    | Other API error             | Say what failed in plain words (e.g. "that language isn't supported", "the organization is out of credits"). The specific reason is in stderr — summarise, don't paste. |
| 5    | Waiting timed out            | "This is taking longer than expected." It is still running — re-run the same command to keep waiting. |
| 6    | Download / file problem      | The source URL is unreachable or the local file is missing, or an export download was interrupted / failed verification (re-run to resume). |

## Failure JSON

Every failure also prints one line on stdout:

```json
{"status": "failed", "error": {"code": "REVISION_CONFLICT", "message": "...",
 "retryable": false}, "request_id": "..."}
```

| `error.code` | Meaning | What to do |
|---|---|---|
| `AUTH_MISSING` / `AUTH_REJECTED` | key not set / not accepted or lacking permission | see exit 2 / 3 |
| `REVISION_CONFLICT` | the transcript changed since it was read | re-run `inspect_process`, redo the edit — never force |
| `VOICE_DECISION_NEEDED` | `add_language`: a speaker has no voice to reuse (`error.speakers`) | ask the caller, pass `--voice-map` |
| `EXPORT_FAILED` | the render failed on the server (`retryable: true`) | run `export_dub` again |
| `INSUFFICIENT_CREDITS` | a billed action (re-translate / re-voice) was refused | tell the caller; nothing was charged |
| `NETWORK_ERROR` | the connection dropped; the request may or may not have landed (`retryable: true`) | re-run the SAME command — it checks what happened first |
| `SERVER_ERROR` | the server failed (5xx) after the automatic retries (`retryable: true`) | re-run the same command |
| `TIMEOUT` | still running when the wait ended | re-run the SAME command — it keeps waiting, never starts a second job |
| `DOWNLOAD_FAILED` | download interrupted or the file failed verification | re-run `download_export` — it resumes; never export again |
| `API_ERROR` | anything else — `message` says what | explain it plainly |

`request_id` is the server's id for the failing call — quote it to support.

## Interrupted or timed out

Re-run the same command. Each one reconciles with what already happened:
`dub_video` reconnects to the run for this file, `resume_dub` picks up a run
already generating, `add_language` / `regenerate_cards` / `fix_issues` wait for
the job already running, `export_dub` reuses a render of the same revision,
`download_export` resumes the partial file. In a new session, start with
`run_manifest.py list` and `run_manifest.py validate --job-id ...`.

## The run failed

`resume_dub.py` prints `"status": "failed"` with `"next_action": "retry_dub"`.
Run `retry_dub.py --job-id ...`: it resumes from the failed step without
re-charging the steps that succeeded. Never publish a new dub to recover.

- "cannot be retried right now" — the run is not failed, or another language /
  export of the same video is still running. Wait for it.
- Failed again after a retry — stop and relay the error in plain terms.

## Export refused

`export_dub.py` prints `"status": "refused"` (exit 0, nothing rendered) with a
`reason`:

- `blocking_issues` → `list_issues.py`, then `fix_issues.py` or `patch_cards.py`.
- `stale_audio` → cards still speak an old line: `regenerate_cards.py --stale`.
- `revision_changed` → the transcript was edited after review: review again.

Do not use `--force` to get past a refusal the caller has not accepted.

## A language could not be added

`add_language.py` rolls a failed add back (as the editor does), so the same
command can simply be run again. `exists` means the language is already on the
dub — review it instead.

## "Not at the voice gate" on resume

`resume_dub.py` exits 4 with this when the run has not reached the gate yet
(still transcribing) — wait and retry. A run already past the gate is picked up
automatically.

## Download verified only "basic"

`"media_check": "basic"` means ffmpeg is not installed: the MP4 structure was
checked, but not the streams or decoding. Install ffmpeg for the full check, or
say in the reply that only a basic check was done.

## Common HTTP failures

| Symptom                                        | Cause                                                     |
| -------------------------------------------- | ------------------------------------------------------- |
| Every call → 403 `Invalid API key`             | `VITRA_UNIVERSE_API_KEY` is not a valid `uvk_` key.     |
| Every call → 403 `not a member of this organization` | The key's creator was removed from the org the key is bound to. Mint a new key. |
| `publish` → 400 mentioning `tmId`              | The translation-memory step failed; re-run phase 1.     |
| `publish` → 400 unknown `processType`          | Server version mismatch (`VIDEO_TO_SPEECH_TRANSLATION` with `inputData.voiceMode` expected). |
| `export-video` → 403                           | The key's user lacks translate-video **export** permission in that org. |
| Any call → 429 `RATE_LIMITED`                  | The key's 60/minute limit. The scripts wait `Retry-After` and retry automatically; only a repeat 429 surfaces. |
| `publish` / `export-video` → 409 with a key    | The same request is still being processed. Wait, then re-run — it will replay the result. |
| `publish` / `export-video` → 422 with a key    | An idempotency key was reused for a different request. Scripts derive keys from the inputs, so this means inputs changed mid-run. |
