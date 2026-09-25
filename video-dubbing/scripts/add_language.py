#!/usr/bin/env python3
"""Add ONE target language to an existing dub — same video, same speakers.

Reuses everything the dub already has: the transcript (including any source
corrections), the speaker map, and each speaker's voice. Nothing is uploaded,
transcribed or cloned again, and no second dub is created.

  GET  .../process-log/{jobId}/status              speakers + their voices
  POST .../process-log/{jobId}/add-language        { targetLanguage,
         diarization: true, voices: {speakerId: voice}, expectedSourceRevision }
  GET  .../process-log/{jobId}/pending-children    wait for the new language
  POST .../process-log/{jobId}/rollback-add-language   only if it failed

Voices, per speaker, in the order the editor uses:
  1. a choice saved for this dub (run manifest voice_map, or --voice-map)
  2. the speaker's own cloned voice from a language already dubbed
  3. any voice the speaker already has in another language
A speaker with none of these stops the command with a question — a voice is
never substituted silently.

Pass --expected-revision (from inspect_process) after correcting the source:
if the transcript changed since, the server refuses (409) rather than
translating a source nobody reviewed.

Prints JSON:
  { "status": "review_ready" | "failed", "job_id", "language",
    "voices": {speakerId: voiceName}, "next_action": ... }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402
import _jobs  # noqa: E402
import _voices  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
STATUS_PATH = PL + "/{job_id}/status"
ADD_PATH = PL + "/{job_id}/add-language"
ROLLBACK_PATH = PL + "/{job_id}/rollback-add-language"
OPERATION = "ADD_LANGUAGE"

DEFAULT_MAX_WAIT = 2400  # transcreate + speech for one language

die = _common.die


def get_status(base: str, headers: dict, job_id: str) -> dict:
    try:
        status, payload = _http.get_json(base + STATUS_PATH.format(job_id=job_id), headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the dub: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this dub"))
    if status == 404:
        die(_common.EXIT_API_ERROR, "that dub was not found in this organization.")
    if status != 200:
        die(_common.EXIT_API_ERROR, f"could not read the dub ({status}): {_common.api_message(payload)}")
    return payload if isinstance(payload, dict) else {}


def _voice(profile: dict) -> dict:
    """The fields add-language keeps (see toSpeakerProfile on the server)."""
    out = {k: profile.get(k) for k in ("voiceId", "voiceName", "voiceType", "gender")}
    if profile.get("provider") is not None:
        out["provider"] = profile["provider"]
    return {k: v for k, v in out.items() if v not in (None, "")}


def saved_voice(per_lang: dict, source_lang: str) -> dict | None:
    """Mirror of the editor's getSavedVoiceForSpeaker: own clone first."""
    langs = [lang for lang in per_lang if lang != source_lang]
    for lang in langs:
        p = per_lang.get(lang) or {}
        if p.get("voiceType") == "instant-clone" and p.get("voiceId"):
            return _voice(p)
    for lang in langs:
        p = per_lang.get(lang) or {}
        if p.get("voiceId") or p.get("voiceName"):
            return _voice(p)
    return None


def build_voices(
    status_row: dict, lang: str, voice_map: dict, clones: list[dict] | None = None
) -> tuple[dict, list[str]]:
    """(voices per speaker, speakers with no voice to reuse)."""
    input_data = status_row.get("inputData") or {}
    speakers = input_data.get("speakers") or {}
    source_lang = status_row.get("sourceLanguage") or ""
    clones = clones or []
    voices: dict = {}
    missing: list[str] = []
    for sid, per_lang in speakers.items():
        per_lang = per_lang if isinstance(per_lang, dict) else {}
        choice = (voice_map.get(sid) or {}).get(lang) or (voice_map.get(sid) or {}).get("*")
        if choice and choice not in ("clone", "keep"):
            # An explicit saved / catalog voice id for this speaker.
            label = (per_lang.get(source_lang) or {}).get("label") or f"Speaker {sid}"
            voices[sid] = _voices.as_voice(choice, clones, label)
            continue
        reuse = saved_voice(per_lang, source_lang)
        if reuse and reuse.get("voiceId") and not reuse.get("voiceType"):
            reuse = {**_voices.as_voice(reuse["voiceId"], clones, reuse.get("voiceName") or ""),
                     **({"gender": reuse["gender"]} if reuse.get("gender") else {})}
        if reuse:
            voices[sid] = reuse
        else:
            missing.append(sid)
    return voices, missing


def rollback(base: str, headers: dict, job_id: str, lang: str) -> None:
    """Undo a failed add so the language can be tried again (as the editor does)."""
    try:
        _http.post_json(base + ROLLBACK_PATH.format(job_id=job_id), headers, {"targetLanguage": lang})
    except _http.NetworkError:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Add one target language to an existing dub.")
    parser.add_argument("--job-id", required=True, help="The dub's job id.")
    parser.add_argument("--language", required=True, help="Language key to add, e.g. tamil_india.")
    parser.add_argument(
        "--voice-map",
        help='JSON: {"<speakerId>": {"<lang>|*": "<voiceId>"}}. Omit to reuse each '
             "speaker's existing voice.",
    )
    parser.add_argument(
        "--expected-revision",
        type=int,
        help="Transcript revision the source was reviewed at (inspect_process).",
    )
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()
    lang = args.language
    saved = _common.load_manifest(args.job_id)

    status_row = get_status(base, headers, args.job_id)
    if status_row.get("sourceLanguage") == lang:
        die(_common.EXIT_API_ERROR, f"{lang} is the video's own language.")

    child_id = None
    if lang in (status_row.get("targetLanguages") or []):
        # Already on the dub: either being added right now (wait for it — do
        # not start a second one) or already there.
        # Already on the dub. Its latest add job says how that went: still
        # running (wait — never start a second), failed (roll back, report),
        # or done / added some other way (nothing to do).
        latest = next(
            (r for r in _jobs.list_children(base, headers, args.job_id)
             if r.get("operation") == OPERATION and r.get("language") == lang),
            None,
        )
        voices = {}
        if latest is not None:
            # Recovered after a lost reply: record it as if this run added it.
            _common.update_manifest(args.job_id, languages={lang: {
                "add_job": latest["id"],
                "status": {"DONE": "review_ready", "FAILED": "failed"}.get(latest.get("status"), "running"),
            }})
        if latest is None or latest.get("status") == _jobs.DONE:
            print(json.dumps({
                "status": "exists" if latest is None else "review_ready",
                "job_id": args.job_id, "language": lang,
                "next_action": "list_issues" if latest else "inspect_process",
            }))
            return _common.EXIT_OK
        child_id = latest["id"]
        if latest.get("status") != _jobs.FAILED:
            sys.stderr.write(f"[add-language] {lang} is already being added; waiting for it\n")
    else:
        try:
            voice_map = json.loads(args.voice_map) if args.voice_map else saved.get("voice_map") or {}
        except ValueError:
            die(_common.EXIT_API_ERROR, "--voice-map must be JSON")
        voices, missing = build_voices(status_row, lang, voice_map, _voices.list_cloned(base, headers))
        if missing:
            die(
                _common.EXIT_API_ERROR,
                "no voice to reuse for speaker(s) "
                + ", ".join(f"Speaker {s}" for s in missing)
                + f" in {lang}. Ask the caller which voice to use and pass --voice-map.",
                error_code="VOICE_DECISION_NEEDED",
                speakers=missing,
            )
        if not voices:
            die(_common.EXIT_API_ERROR, "this dub has no speakers to voice yet.")

        body: dict = {"targetLanguage": lang, "diarization": True, "voices": voices}
        if args.expected_revision is not None:
            body["expectedSourceRevision"] = args.expected_revision
        key = _common.idempotency_key(
            "add-language", args.job_id, lang, json.dumps(voices, sort_keys=True),
            args.expected_revision,
        )
        try:
            status, payload = _http.post_json(
                base + ADD_PATH.format(job_id=args.job_id),
                {**headers, "Idempotency-Key": key},
                body,
            )
        except _http.NetworkError as e:
            die(_common.EXIT_API_ERROR, f"network error adding {lang}: {e}")
        if status in (401, 403):
            die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "add a language"))
        if status == 409:
            die(
                _common.EXIT_API_ERROR,
                f"not added: {_common.api_message(payload)}",
                error_code="REVISION_CONFLICT",
            )
        if status not in (200, 201):
            die(_common.EXIT_API_ERROR, f"could not add {lang} ({status}): {_common.api_message(payload)}")
        child_id = (payload or {}).get("id")
        if not child_id:
            die(_common.EXIT_API_ERROR, "the server did not return the new language's job.")
        _common.update_manifest(args.job_id, languages={lang: {"add_job": child_id, "status": "running"}})

    row = _jobs.wait_for_child(
        base, headers, args.job_id, child_id, f"add {lang}", args.max_wait
    )
    if row.get("status") == _jobs.FAILED:
        rollback(base, headers, args.job_id, lang)
        _common.update_manifest(args.job_id, languages={lang: {"add_job": child_id, "status": "failed"}})
        print(json.dumps({
            "status": "failed", "job_id": args.job_id, "language": lang,
            "error": row.get("errorMessage") or "adding the language failed",
            # Rolled back, so the same command can simply be run again.
            "next_action": "add_language",
        }))
        return _common.EXIT_API_ERROR

    _common.update_manifest(args.job_id, languages={lang: {"add_job": child_id, "status": "review_ready"}})
    print(json.dumps({
        "status": "review_ready",
        "job_id": args.job_id,
        "language": lang,
        "voices": {sid: v.get("voiceName") or v.get("voiceId") for sid, v in voices.items()},
        "next_action": "list_issues",
    }))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
