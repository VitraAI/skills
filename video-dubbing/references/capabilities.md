# Capability matrix — video-dubbing

Every command, the endpoints it calls, and the backend contract it relies on.
All paths are under `/v1/galaxy/translate-video/` unless shown in full. "Optional
server feature" marks behaviour added for this skill; each is opt-in, so a
server without it still works (the script falls back, as noted).

## Commands → endpoints

| Command | Endpoints | Notes |
|---|---|---|
| `list_languages.py` | `GET /v1/language` | |
| `list_providers.py`, `list_tms.py` | `GET /v1/translation-memory/providers`, `GET /v1/translation-memory` | |
| `list_assets.py` | `GET upload?checksum=` / `?keyword=`, `GET process-log?uploadId=` | uploadId filter probed first (older servers ignore it) |
| `dub_video.py` | `GET upload?checksum=`, `POST upload`, `GET process-log?uploadId=`, `POST process-log/publish` (`Idempotency-Key`), `GET process-log/{id}/status`, `GET voice/cloned` | emotion detection on by default; reconciles before publishing |
| `resume_dub.py` | `GET …/{id}/status`, `POST …/{id}/human-validation` | stops at `review_ready`; never exports |
| `retry_dub.py` | `POST …/{id}/retry`, `GET …/{id}/status` | |
| `inspect_process.py` | `GET …/{id}/status`, `GET …/{id}/editor-output?includeRevision=true`, `GET …/{id}/pending-children`, `GET /v1/credits/balance` | balance is null when the key can't read credits |
| `get_card_media.py` | `GET …/{id}/editor-output`, the card's audio url | no separate playback file exists (see below) |
| `patch_cards.py` | `POST process-log/transcript/action`: `update`, `updateEmotion`, `updateRate`, `updateKeepSource`, `updateLipSync`, `updateReviewStatus`, `saveAudio` | each with `expectedRevision`; chains on `X-Transcript-Revision` |
| `card_ops.py` | `transcript/action`: `split`, `merge`, `add`, `delete`; `PUT …/{id}/assign-speaker`; `POST …/{id}/speakers`; `PUT …/{id}/speaker-voice`; `POST process-log/sync-services/action`: `text-translation`, `text-to-speech`; `POST process-log/subtitle/action`: `updateById`, `delete`, `split`, `merge` | structural + subtitle actions revision-guarded; billed sync actions are not |
| `regenerate_cards.py` | `POST …/{id}/generate-all` `{transcriptIds}`, `GET …/{id}/pending-children` | verifies by hashing the audio (same url after regeneration) |
| `add_language.py` | `POST …/{id}/add-language` (`Idempotency-Key`, `expectedSourceRevision`), `GET …/{id}/pending-children`, `POST …/{id}/rollback-add-language` | voices reused per speaker like the editor |
| `list_issues.py` | `GET process-log/transcript/issues?id&lang` | |
| `fix_issues.py` | `transcript/issues`, `POST …/{id}/autofix-all`, `POST …/{id}/generate-all`, `pending-children`, `editor-output` | bounded; discloses every change |
| `export_dub.py` | `transcript/issues`, `editor-output?includeRevision=true`, `POST process-log/export-video` (`Idempotency-Key`), `GET …/{exportId}/editor-output`, `pending-children` | refuses on issues / stale audio / moved revision |
| `download_export.py` | `GET …/{exportId}/editor-output`, `POST process-log/presigned-export-url` | Range resume; ffprobe/ffmpeg checks when installed |
| `run_manifest.py` | local file; `validate` adds `status` + `editor-output` | |

## Backend contracts

| Contract | Status | How |
|---|---|---|
| Asset lookup by SHA-256 / name | ✅ | `upload?checksum=` / `keyword=`; hash stored for direct and multipart uploads |
| Process lookup by asset | ✅ optional server feature | `process-log?uploadId=` |
| Editor read with revision | ✅ optional server feature | `editor-output?includeRevision=true` |
| Card edit with `expectedRevision`, new revision returned | ✅ optional server feature | transcript + subtitle actions; `X-Transcript-Revision` header |
| Stale audio after an edit | ✅ client-side | computed from the edit (text/emotion) and kept in the run record |
| Selective regeneration | ✅ | `generate-all` with `transcriptIds`; per card: `sync-services text-to-speech` |
| Add language, source-revision check | ✅ optional server feature | `expectedSourceRevision`; `Idempotency-Key` |
| Issues + bounded repair | ✅ | `transcript/issues` + `autofix-all` / scoped `generate-all` |
| Card media (source window, raw audio) | ✅ | raw clip = `a.url`; playback transforms reported, not a file |
| Export idempotent per revision | ✅ optional server feature | `Idempotency-Key` from language + resolution + revision |
| Retry a failed run in place | ✅ optional server feature | `POST …/{id}/retry` |
| Idempotency keys stored server-side | ✅ optional server feature | `publish`, `add-language`, `export-video` |
| 429 with `Retry-After` | ✅ | scripts wait (with jitter) and retry |
| Polling guidance | ✅ optional server feature | `nextPollAfterSeconds` on status |
| Request id | ✅ | `x-request-id` on every response; in every failure JSON |
| Credits | ✅ | balance from `credits/balance`; unknown stays null |

## Not covered (known backend dependencies)

- **Per-generation id / input revision on a card's audio.** The server keeps no
  generation id, so "is this audio current?" is answered by hashing the file and
  by the skill's own stale list — not by the server.
- **A playback-adjusted audio file.** Rate and volume are applied by the
  player/renderer; there is no file to fetch.
- **`validate_only` on the server.** `patch_cards --dry-run` validates locally
  against the current cards instead.
- **Per-run usage (credits spent by this dub).** Only the balance is exposed.
- **Pronunciation and audio-integrity QC, and final multimodal QC** — out of
  scope for now.
