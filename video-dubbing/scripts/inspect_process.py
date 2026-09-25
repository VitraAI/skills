#!/usr/bin/env python3
"""Read the current state of a dub: stage, languages, speakers, cards, exports.

The read half of the review step. Run this after `resume_dub.py` reaches
`review_ready` and before `export_dub.py`, so the agent is deciding from what
the server actually holds rather than from what it remembers publishing.

  GET .../process-log/{id}/status        -> stage, progress, status
  GET .../process-log/{id}/editor-output -> transcripts, speakers, settings

Prints JSON:
  { "status": "...", "process_id": "...", "stage": "...",
    "source_language": "...", "target_languages": [...],
    "speakers": [...], "cards": {"<lang>": {"total": 12, "with_audio": 11}},
    "exports": [...], "next_action": "list_issues" }

Add `--cards <lang>` to also print every card for one language — id, text,
speaker, emotion, rate and current audio — which is what `patch_cards` needs
to target a change.

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
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

PL = "/v1/galaxy/translate-video/process-log"
STATUS_PATH = PL + "/{job_id}/status"
EDITOR_OUTPUT_PATH = PL + "/{job_id}/editor-output"

die = _common.die


def fetch(base: str, headers: dict, path: str, label: str) -> dict:
    try:
        status, payload = _http.get_json(base + path, headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading {label}: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, f"read {label}"))
    if status == 404:
        die(_common.EXIT_API_ERROR, "that dub was not found in this organization.")
    if status != 200:
        die(
            _common.EXIT_API_ERROR,
            f"could not read {label} ({status}): {_common.api_message(payload)}",
        )
    body = payload if isinstance(payload, dict) else {}
    inner = body.get("data")
    return inner if isinstance(inner, dict) else body


def transcripts_of(editor: dict) -> list:
    """Cards live at `data.OUTPUT[0].transcripts` in the editor payload.

    The document is the `{ OUTPUT: [root] }` envelope the aggregate worker
    writes — reading `data.transcripts` directly finds nothing and reports every
    dub as having zero cards.
    """
    data = editor.get("data") if isinstance(editor.get("data"), dict) else editor
    out = data.get("OUTPUT")
    if isinstance(out, list) and out and isinstance(out[0], dict):
        data = out[0]
    rows = data.get("transcripts")
    return rows if isinstance(rows, list) else []


def card_summary(rows: list, lang: str) -> dict:
    """How many cards exist for a language, and how many already have audio.

    `with_audio` is the number that would survive an export today — a card whose
    `a.url` is missing is the "missing audio" case the issue list reports.
    """
    total = with_audio = 0
    for row in rows:
        if not isinstance(row, dict):
            continue
        block = row.get(lang)
        if not isinstance(block, dict):
            continue
        total += 1
        audio = block.get("a")
        if isinstance(audio, dict) and audio.get("url"):
            with_audio += 1
    return {"total": total, "with_audio": with_audio}


def describe_cards(rows: list, lang: str) -> list:
    """One entry per card — enough for the agent to choose what to patch."""
    out = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        block = row.get(lang)
        if not isinstance(block, dict):
            continue
        tr = block.get("tr") if isinstance(block.get("tr"), dict) else {}
        audio = block.get("a") if isinstance(block.get("a"), dict) else {}
        video = block.get("v") if isinstance(block.get("v"), dict) else {}
        out.append(
            {
                "card_id": row.get("id"),
                "text": tr.get("text"),
                "speaker": block.get("speakerId") or row.get("speakerId"),
                "emotion": block.get("emotion"),
                "keep_source": bool(block.get("keepSourceAudio")),
                "lip_sync": bool(block.get("isLipSync")),
                "review_status": block.get("rs"),
                "start": video.get("st"),
                "end": video.get("et"),
                # Raw audio plus the rate applied at playback — the rate is not
                # baked into the file, so report both rather than conflating.
                "audio": {
                    "url": audio.get("url"),
                    # `a.d` is SECONDS (a 4s clip reads 4.47), not ms.
                    "duration_seconds": audio.get("d"),
                    "audio_rate": audio.get("r"),
                },
            }
        )
    return out


def running_jobs(base: str, headers: dict, job_id: str) -> list:
    """Unfinished background jobs (add language, regenerate, fix, export)."""
    import _jobs

    return [
        {"job_id": r.get("id"), "operation": r.get("operation"),
         "language": r.get("language"), "status": r.get("status"), "progress": r.get("progress")}
        for r in _jobs.list_children(base, headers, job_id)
        if r.get("status") not in (_jobs.DONE, _jobs.FAILED)
    ]


def usage(base: str, headers: dict) -> dict:
    """The organization's credit balance. Unknown stays null, never 0 — the key
    may simply lack permission to read credits."""
    try:
        status, payload = _http.get_json(base + "/v1/credits/balance", headers=headers)
    except _http.NetworkError:
        status, payload = 0, None
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else payload
    balance = data.get("balance") if status == 200 and isinstance(data, dict) else None
    return {"credit_balance": balance if isinstance(balance, (int, float)) else None}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read the current state of a dub before reviewing or exporting."
    )
    parser.add_argument("--job-id", required=True, help="The dub's job id.")
    parser.add_argument(
        "--cards",
        metavar="LANGUAGE_KEY",
        help="Also print every card for this language (id, text, emotion, audio).",
    )
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    status_row = fetch(
        base, headers, STATUS_PATH.format(job_id=args.job_id), "dub status"
    )
    editor = fetch(
        base,
        headers,
        EDITOR_OUTPUT_PATH.format(job_id=args.job_id) + "?includeRevision=true",
        "editor output",
    )

    rows = transcripts_of(editor)
    targets = status_row.get("targetLanguages") or []
    if isinstance(targets, str):
        targets = [targets]

    result = {
        "status": "ok",
        "process_id": args.job_id,
        "stage": status_row.get("stage") or status_row.get("activeTaskIdentifier"),
        # Pass to patch_cards as --revision so an edit made against a stale read
        # is refused instead of overwriting someone else's change.
        "revision": editor.get("revision"),
        "run_status": status_row.get("status"),
        "progress": status_row.get("progress"),
        "source_language": status_row.get("sourceLanguage"),
        "target_languages": targets,
        "cards": {lang: card_summary(rows, lang) for lang in targets},
        # What the run was actually created with, read back rather than assumed.
        "settings": {
            "emotion_detection": bool((status_row.get("inputData") or {}).get("emotionDetection")),
            "multi_speaker": bool((status_row.get("inputData") or {}).get("multiSpeaker")),
        },
        "background_jobs": running_jobs(base, headers, args.job_id),
        "usage": usage(base, headers),
        "next_action": "list_issues",
    }
    saved = _common.load_manifest(args.job_id)
    if saved:
        result["checkpoint"] = str(_common.manifest_path(args.job_id))
        result["audio_stale"] = {k: v for k, v in (saved.get("audio_stale") or {}).items() if v}
        result["exports"] = {
            lang: {k: e.get(k) for k in ("export_id", "revision", "resolution")}
            for lang, e in (saved.get("exports") or {}).items()
        }

    if args.cards:
        if args.cards not in targets:
            sys.stderr.write(
                f"[warn] '{args.cards}' is not a target language of this dub "
                f"({', '.join(targets) or 'none'})\n"
            )
        result["card_detail"] = {args.cards: describe_cards(rows, args.cards)}

    print(json.dumps(result))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
