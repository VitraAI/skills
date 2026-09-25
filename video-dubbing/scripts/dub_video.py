#!/usr/bin/env python3
"""Phase 1 of a translate-video dub: upload the video and start the run,
then poll to the speaker-voice review gate and print the detected speakers.

Flow:
  1. resolve the source (--file or --url; a URL is downloaded to a temp file)
  2. POST multipart to /v1/galaxy/translate-video/upload            -> uploadId
  3. find or create a translation memory for the run                -> tmId
  4. POST /v1/galaxy/translate-video/process-log/publish            -> jobId
  5. poll /v1/galaxy/translate-video/process-log/{jobId}/status
     until awaitingHumanValidation is true (or the run fails early)
  6. print JSON: { status:"awaiting_voices", job_id, task_identifier,
                   target_languages, speakers:[...], saved_cloned_voices:[...],
                   checkpoint }

Never starts the same dub twice. Before publishing it looks for an existing run
of this file — first in the local run manifest, then on the server (runs made
from the same upload with the same languages). A run found past the gate is
reported as-is (`review_ready` / `running`) instead of being re-published.
`--new-run` skips that and always starts a fresh one.

Emotion detection is ON by default (each line's emotion is detected and voiced;
still reviewable per card). `--no-emotion-detection` turns it off.

The caller reviews the speakers, picks a voice per speaker per target
language, then runs resume_dub.py with --job-id and --voice-map.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import os
import tempfile
import time
from pathlib import Path
from urllib.parse import urlencode, urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _tm  # noqa: E402

UPLOAD_PATH = "/v1/galaxy/translate-video/upload"
TM_PATH = "/v1/translation-memory"
# The provider the server uses when it creates a run's TM itself.
DEFAULT_TM_PROVIDER = "vitratm"
PUBLISH_PATH = "/v1/galaxy/translate-video/process-log/publish"
STATUS_PATH = "/v1/galaxy/translate-video/process-log/{job_id}/status"
LIST_PATH = "/v1/galaxy/translate-video/process-log"
CLONED_VOICES_PATH = "/v1/galaxy/translate-video/voice/cloned"

# THE dubbing type. Cloning is an option on the run, not a separate type:
# `inputData.voiceMode: "instant_clone"` (the separate *_WITH_INSTANT_VOICE_CLONE
# type was retired by the MergeDubbingProcessTypes migration).
PROCESS_TYPE = "VIDEO_TO_SPEECH_TRANSLATION"
VOICE_MODE = "instant_clone"
DEFAULT_POLL_INTERVAL = 12
DEFAULT_MAX_WAIT = 1800  # 30 min to reach the gate

FAILED_STATUSES = {"FAILED", "ERROR", "CANCELLED"}

die = _common.die


def resolve_source(file_arg: str | None, url_arg: str | None) -> tuple[Path, bool]:
    """Return (local_path, is_temp). Downloads a URL to a temp file."""
    if file_arg:
        p = Path(file_arg).expanduser()
        if not p.is_file():
            die(_common.EXIT_DOWNLOAD, f"--file not found: {p}")
        return p, False

    parsed = urlparse(url_arg or "")
    if parsed.scheme not in ("http", "https"):
        die(_common.EXIT_DOWNLOAD, "--url must be an http(s) URL")
    name = Path(parsed.path).name or "video.mp4"
    tmp = Path(tempfile.gettempdir()) / f"vitra-dub-{os.getpid()}-{name}"
    try:
        # No size cap: the translate-video upload API imposes none, and a
        # feature-length video legitimately runs to many GB. Failing a valid
        # dub on a limit the product does not have is the worse outcome.
        n = _http.download_to_file(url_arg, tmp)
    except _http.NetworkError as e:
        die(_common.EXIT_DOWNLOAD, f"could not download --url: {e}")
    except ValueError as e:
        die(_common.EXIT_DOWNLOAD, str(e))
    sys.stderr.write(f"[source] downloaded {n} bytes -> {tmp}\n")
    return tmp, True


def find_existing_upload(base: str, headers: dict, sha256: str) -> str | None:
    """A previous upload of exactly these bytes, if the server has one.

    Best-effort: any failure (older server without checksum lookup, network)
    just means we upload again — never a reason to stop.
    """
    try:
        status, payload = _http.get_json(
            f"{base}{UPLOAD_PATH}?{urlencode({'checksum': sha256, 'limit': 1})}",
            headers=headers,
        )
    except _http.NetworkError:
        return None
    if status != 200 or not isinstance(payload, dict):
        return None
    for row in payload.get("data") or payload.get("uploads") or []:
        if row.get("id") and row.get("sha256") == sha256:
            return row["id"]
    return None


def upload(base: str, headers: dict, path: Path) -> str:
    try:
        status, payload = _http.post_multipart_json(
            base + UPLOAD_PATH, headers, "files", path
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error uploading: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"upload failed ({status}): {_common.api_message(payload)}")
    uploads = (payload or {}).get("uploads") or []
    if not uploads or not uploads[0].get("id"):
        die(_common.EXIT_API_ERROR, f"no upload id in response: {_common.api_message(payload)}")
    return uploads[0]["id"]


def tm_name_for(source_language: str, target_languages: list[str]) -> str:
    """Deterministic name for a language pair/set.

    Named from the LANGUAGES, never the video filename — a per-file name makes
    every run a fresh memory, which defeats the point: wording approved on one
    dub should carry into the next dub of the same languages.
    """
    return f"dub · {source_language} → {', '.join(sorted(target_languages))}"


def find_or_create_tm(
    base: str,
    headers: dict,
    name: str,
    source_language: str,
    target_languages: list[str],
    provider: str = "vitratm",
) -> str:
    try:
        status, payload = _http.get_json(
            f"{base}{TM_PATH}?{urlencode({'search': name})}", headers=headers
        )
        if status == 200:
            rows = payload if isinstance(payload, list) else payload.get("data", [])
            for row in rows:
                if row.get("name") == name and row.get("id"):
                    sys.stderr.write(f"[tm] reusing {row['id']}\n")
                    return row["id"]
    except _http.NetworkError:
        pass

    body = {
        "name": name,
        "sourceLanguage": source_language,
        "targetLanguages": target_languages,
        "tmMode": "create",
        "provider": provider,
    }
    try:
        status, payload = _http.post_json(base + TM_PATH, headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error creating TM: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "create a translation memory"))
    if status == 409:
        s2, p2 = _http.get_json(
            f"{base}{TM_PATH}?{urlencode({'search': name})}", headers=headers
        )
        rows = p2 if isinstance(p2, list) else (p2 or {}).get("data", [])
        for row in rows:
            if row.get("name") == name and row.get("id"):
                return row["id"]
        die(_common.EXIT_API_ERROR, "TM name conflict but could not resolve the existing TM")
    if status not in (200, 201) or not (payload or {}).get("id"):
        die(_common.EXIT_API_ERROR, f"TM create failed ({status}): {_common.api_message(payload)}")
    sys.stderr.write(f"[tm] created {payload['id']}\n")
    return payload["id"]


def publish(
    base: str,
    headers: dict,
    upload_id: str,
    run_name: str,
    source_language: str,
    target_languages: list[str],
    tm_id: str | None,
    idempotency_key: str,
    emotion_detection: bool = True,
) -> str:
    body = {
        "processType": PROCESS_TYPE,
        "processName": run_name,
        "uploadIds": [upload_id],
        "sourceLanguage": source_language,
        "targetLanguages": target_languages,
        "metadata": {"source": "skill:video-dubbing"},
        # Diarization config — MUST be sent at publish or the transcription
        # stage runs single-speaker and the voice gate opens with no speakers.
        # Mirrors the webapp's publish payload verbatim.
        "inputData": {
            "voiceMode": VOICE_MODE,
            "multiSpeaker": True,
            "speakerCount": "auto-detect",
            "emotionDetection": emotion_detection,
            "compress": True,
        },
    }
    if tm_id:
        # Omitted, the server finds-or-creates the `dub · <source> → <targets>`
        # memory itself (the same name `tm_name_for` builds).
        body["tmId"] = tm_id
    try:
        status, payload = _http.post_json(
            base + PUBLISH_PATH,
            {**headers, "Idempotency-Key": idempotency_key},
            body,
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error on publish: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"publish failed ({status}): {_common.api_message(payload)}")
    job_id = (payload or {}).get("processId") or (payload or {}).get("jobId")
    if not job_id:
        die(_common.EXIT_API_ERROR, f"no processId in publish response: {_common.api_message(payload)}")
    return job_id


def poll_to_gate(
    base: str, headers: dict, job_id: str, poll_interval: int, max_wait: int
) -> dict:
    url = base + STATUS_PATH.format(job_id=job_id)
    deadline = time.monotonic() + max_wait
    delays = _http.poll_delays(first=poll_interval)
    last = None
    while True:
        try:
            status, payload = _http.get_json(url, headers=headers)
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error polling status: {e}")
        if status != 200:
            die(_common.EXIT_API_ERROR, f"status poll failed ({status}): {_common.api_message(payload)}")

        state = (payload or {}).get("status")
        if state != last:
            sys.stderr.write(f"[poll] job={job_id} status={state}\n")
            last = state

        if payload.get("awaitingHumanValidation"):
            return payload
        # A reused run may already be past the gate; the caller reports it.
        if payload.get("isFinished") and str(state).lower() == "completed":
            return payload
        if payload.get("isFinished") or str(state).upper() in FAILED_STATUSES:
            die(
                _common.EXIT_API_ERROR,
                "run finished before the voice gate: "
                + json.dumps(
                    {
                        "errorCode": payload.get("errorCode"),
                        "errorMessage": payload.get("errorMessage"),
                    }
                ),
            )
        if time.monotonic() >= deadline:
            die(
                _common.EXIT_TIMEOUT,
                f"timed out after {max_wait}s waiting for the voice gate. "
                f"job_id={job_id} — re-run resume_dub.py once it reaches the gate.",
            )
        time.sleep(_http.next_poll(payload, delays))


def _run_is_usable(row: dict) -> bool:
    return str(row.get("status", "")).lower() not in ("failed", "cancelled")


def find_existing_run(
    base: str, headers: dict, upload_id: str, source_language: str, targets: list[str]
) -> str | None:
    """A live run already made from this upload with the same languages.

    Needs a server that understands `?uploadId=`. An older one ignores unknown
    filters and would return every run, so support is probed first with an id
    that cannot match: a server that filters returns nothing for it.
    """
    import uuid

    def query(upload: str, limit: int) -> list | None:
        q = urlencode({"uploadId": upload, "limit": limit, "sortBy": "createdAt", "sortOrder": "DESC"})
        try:
            status, payload = _http.get_json(f"{base}{LIST_PATH}?{q}", headers=headers)
        except _http.NetworkError:
            return None
        if status != 200 or not isinstance(payload, dict):
            return None
        rows = payload.get("data")
        return rows if isinstance(rows, list) else None

    probe = query(str(uuid.uuid4()), 1)
    if probe is None or probe:
        return None  # lookup unsupported here; rely on the idempotency key
    for row in query(upload_id, 20) or []:
        if not isinstance(row, dict) or not _run_is_usable(row):
            continue
        if row.get("sourceLanguage") == source_language and sorted(
            row.get("targetLanguages") or []
        ) == sorted(targets):
            return row.get("id")
    return None


def run_state(base: str, headers: dict, job_id: str) -> dict | None:
    try:
        status, payload = _http.get_json(base + STATUS_PATH.format(job_id=job_id), headers=headers)
    except _http.NetworkError:
        return None
    return payload if status == 200 and isinstance(payload, dict) else None


def list_cloned_voices(base: str, headers: dict) -> list[dict]:
    """The org's saved instant-clone voices — offered for reuse per speaker."""
    import _voices

    return _voices.list_cloned(base, headers)


def shape_speakers(status_payload: dict) -> list[dict]:
    speakers = ((status_payload.get("inputData") or {}).get("speakers")) or {}
    previews = ((status_payload.get("inputData") or {}).get("speakerPreview")) or {}
    out = []
    for sid, per_lang in speakers.items():
        label, gender = "", ""
        for slot in (per_lang or {}).values():
            label = label or (slot or {}).get("label") or ""
            gender = gender or (slot or {}).get("gender") or ""
        windows = previews.get(sid) or []
        first = windows[0] if windows else {}
        out.append(
            {
                "speaker_id": sid,
                "label": label or f"Speaker {sid}",
                "gender": gender,
                "preview": {"st": first.get("st"), "et": first.get("et")},
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Phase 1: upload + start dub, stop at the voice gate."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="Local video file path.")
    src.add_argument("--url", help="Public http(s) video URL (downloaded, then uploaded).")
    parser.add_argument(
        "--source-language",
        required=True,
        metavar="KEY",
        help=(
            "Source language key from list_languages.py (e.g. english_united_states). "
            "Required — 'auto' is NOT supported (transcreation needs a concrete language)."
        ),
    )
    parser.add_argument(
        "--target-language",
        action="append",
        required=True,
        metavar="KEY",
        help="Target language key (repeat for several).",
    )
    parser.add_argument("--name", help="Process display name. Defaults to the file name.")
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument(
        "--tm-provider",
        default=DEFAULT_TM_PROVIDER,
        help="Provider for an auto-created TM. Only offer one that "
             "list_providers.py reports as available.",
    )
    tm = parser.add_mutually_exclusive_group()
    tm.add_argument(
        "--tm-name",
        help="Translation Memory to reuse, by the name list_tms.py shows. Omit to "
             "find-or-create the one for this language pair. See SKILL.md — list "
             "first, then ask.",
    )
    # Internal handle kept for older callers; people choose by name.
    tm.add_argument("--tm-id", help=argparse.SUPPRESS)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    parser.add_argument(
        "--no-emotion-detection",
        action="store_true",
        help="Voice every line neutrally instead of detecting each line's emotion.",
    )
    parser.add_argument(
        "--new-run",
        action="store_true",
        help="Always start a new dub, even if one for this file and these "
             "languages already exists.",
    )
    args = parser.parse_args()
    emotion_detection = not args.no_emotion_detection

    base = _common.base_url()
    headers = _common.headers()
    # Resolve a memory chosen by name before uploading anything, so a typo
    # fails in a second instead of after the upload.
    chosen_tm = args.tm_id or (
        _tm.resolve_by_name(base, headers, args.tm_name) if args.tm_name else None
    )

    path, is_temp = resolve_source(args.file, args.url)
    try:
        run_name = args.name or f"dub · {path.stem}"
        source_language = args.source_language
        if source_language.lower() in ("auto", "auto-detect", "auto_detect"):
            die(
                _common.EXIT_API_ERROR,
                "--source-language must be a concrete language key "
                "(run list_languages.py); 'auto' is not supported.",
            )
        targets = args.target_language

        # Hash first: a re-run of the same file reuses the earlier upload
        # instead of sending the bytes again, and the hash anchors the publish
        # idempotency key below.
        file_sha256 = _common.sha256_file(path)
        upload_id = find_existing_upload(base, headers, file_sha256)
        if upload_id:
            sys.stderr.write(f"[upload] reusing earlier upload {upload_id}\n")
        else:
            upload_id = upload(base, headers, path)
            sys.stderr.write(f"[upload] uploadId={upload_id}\n")

        # A TM the caller chose always wins (see SKILL.md: list, then ask).
        # Otherwise the server finds-or-creates the one for THIS language pair
        # when `tmId` is omitted, so repeat dubs of the same languages share a
        # memory. It always creates with the default provider, so only a
        # different provider the caller picked is still created here.
        tm_id = chosen_tm
        if not tm_id and args.tm_provider != DEFAULT_TM_PROVIDER:
            tm_id = find_or_create_tm(
                base, headers, tm_name_for(source_language, targets),
                source_language, targets, args.tm_provider
            )
        # Same file + same languages + same memory = the same dub. A retried
        # publish (timeout, crash, re-run) gets the first run back instead of
        # starting — and paying for — a second one.
        publish_key = _common.idempotency_key(
            "publish", file_sha256, source_language, sorted(targets), tm_id, run_name,
            emotion_detection, *(["new", time.time()] if args.new_run else []),
        )

        # Reconcile before creating: this machine's manifest first (covers a
        # crash between publish and the gate), then the server (covers another
        # machine or a lost manifest). Either way no second run is paid for.
        job_id = None
        if not args.new_run:
            known = _common.find_manifest(publish_key=publish_key)
            if known and (run_state(base, headers, known["job_id"]) or {}).get("status") not in (
                None, "failed", "cancelled",
            ):
                job_id = known["job_id"]
                sys.stderr.write(f"[reuse] continuing run {job_id} from the manifest\n")
            if not job_id:
                job_id = find_existing_run(base, headers, upload_id, source_language, targets)
                if job_id:
                    sys.stderr.write(f"[reuse] found existing run {job_id} for this file\n")
        if not job_id:
            job_id = publish(
                base, headers, upload_id, run_name, source_language, targets, tm_id,
                publish_key, emotion_detection,
            )
            sys.stderr.write(f"[publish] jobId={job_id}\n")

        checkpoint = _common.update_manifest(
            job_id,
            stage="published",
            source_sha256=file_sha256,
            upload_id=upload_id,
            publish_key=publish_key,
            run_name=run_name,
            source_language=source_language,
            target_languages=targets,
            tm_id=tm_id,
            emotion_detection=emotion_detection,
        )

        status_payload = poll_to_gate(
            base, headers, job_id, args.poll_interval, args.max_wait
        )
    finally:
        if is_temp:
            try:
                path.unlink()
            except OSError:
                pass

    if not status_payload.get("awaitingHumanValidation"):
        # A reused run that is already past the voices.
        _common.update_manifest(job_id, stage="review_ready")
        print(
            json.dumps(
                {
                    "status": "review_ready",
                    "job_id": job_id,
                    "target_languages": status_payload.get("targetLanguages") or targets,
                    "next_action": "inspect_process",
                    "checkpoint": str(checkpoint),
                }
            )
        )
        return _common.EXIT_OK

    _common.update_manifest(job_id, stage="awaiting_voices")
    print(
        json.dumps(
            {
                "status": "awaiting_voices",
                "job_id": job_id,
                "checkpoint": str(checkpoint),
                "task_identifier": status_payload.get("humanValidationTaskIdentifier"),
                "source_language": status_payload.get("sourceLanguage"),
                "target_languages": status_payload.get("targetLanguages") or targets,
                "speakers": shape_speakers(status_payload),
                "saved_cloned_voices": list_cloned_voices(base, headers),
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
