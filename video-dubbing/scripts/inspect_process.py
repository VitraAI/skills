#!/usr/bin/env python3
"""Read the current state of a dub: stage, languages, speakers, cards, exports.

The read half of the review step. Run this after `resume_dub.py` reaches
`review_ready` and before `export_dub.py`, so the agent is deciding from what
the server actually holds rather than from what it remembers publishing.

  GET .../process-log/{id}/status        -> stage, progress, status
  GET .../process-log/{id}/editor-output -> transcripts, speakers, settings

Prints JSON:
  { "status": "ok", "job_id", "revision", "run_status", "progress",
    "source_language", "target_languages",
    "cards":  {"<lang>": {"total": 12, "with_audio": 11, "unreviewed": 4}},
    "issues": {"<lang>": {"errors": 1, "warnings": 2}},
    "suggestions": [{"do", "why", "run", "spends_credits"}],
    "next_action": "..." }

`suggestions` are the next steps worth offering, computed from the data above
(missing or stale audio, blocking issues, unreviewed lines, what is exported):
relay them to the user in order; never run one that spends credits without a
yes.

`--cards <lang>` adds that language's lines, numbered as people see them
(`line`, text, speaker, timing, emotion, audio, review), 50 at a time (`more`
gives the next page): what patch_cards and card_ops take. `--subtitles <lang>`
lists its subtitle lines the same way, for edit_subtitles.py.

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
import _cards  # noqa: E402
import _common  # noqa: E402
import _cue  # noqa: E402
import _http  # noqa: E402
import _progress  # noqa: E402

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

    Reading `data.transcripts` directly finds nothing and would report every
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
    total = with_audio = unreviewed = 0
    for row in rows:
        if not isinstance(row, dict) or row.get("isGap"):
            continue
        block = row.get(lang)
        if not isinstance(block, dict):
            continue
        total += 1
        audio = block.get("a")
        # A Keep Source line plays the original recording on purpose: it has
        # no dubbed audio and needs none.
        if block.get("keepSourceAudio") or (isinstance(audio, dict) and audio.get("url")):
            with_audio += 1
        # `rs`: u unverified (or absent), v verified, a approved.
        if block.get("rs") not in ("v", "a"):
            unreviewed += 1
    return {"total": total, "with_audio": with_audio, "unreviewed": unreviewed}


def describe_cards(rows: list, lang: str) -> list:
    """One entry per line, numbered as people see them; empty fields left out."""
    numbers = _cards.line_numbers(rows)
    out = []
    for row in rows:
        if not isinstance(row, dict) or str(row.get("id")) not in numbers:
            continue
        block = row.get(lang)
        if not isinstance(block, dict):
            continue
        tr = block.get("tr") if isinstance(block.get("tr"), dict) else {}
        audio = block.get("a") if isinstance(block.get("a"), dict) else {}
        video = block.get("v") if isinstance(block.get("v"), dict) else {}
        line = {
            "line": numbers[str(row.get("id"))],
            "text": tr.get("text"),
            "speaker": block.get("speakerId") or row.get("speakerId"),
            "start": video.get("st"),
            "end": video.get("et"),
            "emotion": block.get("emotion"),
            # `a.d` is seconds; the rate is applied at playback, not baked in.
            "audio_seconds": audio.get("d") if audio.get("url") else None,
            "rate": audio.get("r"),
            "review": {"v": "verified", "a": "approved"}.get(block.get("rs"), "unreviewed"),
            "keep_source": bool(block.get("keepSourceAudio")) or None,
            "lip_sync": bool(block.get("isLipSync")) or None,
        }
        out.append({k: v for k, v in line.items() if v is not None})
    return out


def issue_counts(base: str, headers: dict, job_id: str, lang: str) -> dict | None:
    """Blocking errors and warnings for one language; None if unreadable."""
    from urllib.parse import urlencode

    try:
        status, payload = _http.get_json(
            f"{base}{PL}/transcript/issues?{urlencode({'id': job_id, 'lang': lang})}",
            headers=headers,
        )
    except _http.NetworkError:
        return None
    if status != 200 or not isinstance(payload, dict):
        return None
    data = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    count = lambda k: len(data.get(k)) if isinstance(data.get(k), list) else 0  # noqa: E731
    return {"errors": count("errors"), "warnings": count("warnings")}


def suggest(result: dict, job_id: str) -> list[dict]:
    """Next steps worth offering, most urgent first, from verified data only."""
    out: list[dict] = []

    def add(do: str, why: str, run: str, credits: bool) -> None:
        out.append({"do": do, "why": why, "run": run, "spends_credits": credits})

    run_status = str(result.get("run_status") or "").lower()
    if run_status == "failed":
        add("Resume the dub from the step that failed",
            "the run failed; a retry keeps every finished step",
            f"retry_dub.py --job-id {job_id}", True)
        return out
    if result.get("awaiting_voices"):
        add("Ask the user about each speaker's voice, then continue",
            "the dub is waiting for the voice decision",
            f"resume_dub.py --job-id {job_id} --voice-map '<answers>'", True)
        return out
    if run_status not in ("completed", ""):
        add("Wait, then check again",
            f"the dub is still {run_status}",
            f"inspect_process.py --job-id {job_id}", False)
        return out
    if result.get("background_jobs"):
        add("Wait for the running job, then check again",
            "a job is still changing this dub (" + ", ".join(
                j["what"] for j in result["background_jobs"]) + ")",
            f"inspect_process.py --job-id {job_id}", False)
        return out

    exports = result.get("exports") or {}
    revision = result.get("revision")
    rev = f" --revision {revision}" if revision is not None else ""
    stale = result.get("audio_stale") or {}
    for lang in result.get("target_languages") or []:
        cards = (result.get("cards") or {}).get(lang) or {}
        issues = (result.get("issues") or {}).get(lang) or {}
        missing = max(0, int(cards.get("total") or 0) - int(cards.get("with_audio") or 0))
        blocked = False
        if missing:
            blocked = True
            add(f"Generate speech for {missing} {lang} line(s) that have none",
                "lines without audio block the export",
                f"regenerate_cards.py --job-id {job_id} --language {lang} --missing", True)
        if stale.get(lang):
            blocked = True
            add(f"Re-voice {len(stale[lang])} {lang} line(s) that still speak their old version",
                "their emotion changed after the audio was made",
                f"regenerate_cards.py --job-id {job_id} --language {lang} --stale", True)
        if issues.get("errors") and not missing:
            blocked = True
            add(f"Fix {issues['errors']} blocking issue(s) in {lang}",
                "export is refused while errors remain",
                f"fix_issues.py --job-id {job_id} --language {lang}", False)
        if blocked:
            continue
        if cards.get("unreviewed"):
            add(f"Review {cards['unreviewed']} {lang} line(s) nobody has checked yet",
                "nothing blocks the export, but unchecked lines ship as the machine wrote them",
                f"inspect_process.py --job-id {job_id} --cards {lang}", False)
        done = exports.get(lang) or {}
        if done.get("export_id") and done.get("revision") == revision:
            add(f"Download the {lang} video",
                "it is already exported at the current version",
                f"download_export.py --export-id {done['export_id']} --out ./{lang}.mp4 --job-id {job_id}", False)
        else:
            add(f"Export the {lang} video",
                "no blocking issues remain" + (" (the earlier export is out of date)" if done else ""),
                f"export_dub.py --job-id {job_id} --language {lang}{rev}", True)
    return out


def running_jobs(base: str, headers: dict, job_id: str) -> list:
    """Unfinished background jobs (add language, regenerate, fix, export)."""
    import _jobs

    return [
        {"what": _jobs.describe(r), "progress": r.get("progress")}
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
        help="Also list this language's lines (text, speaker, timing, emotion, audio).",
    )
    parser.add_argument(
        "--subtitles", metavar="LANGUAGE_KEY",
        help="Also list this language's subtitle lines (for edit_subtitles.py).",
    )
    parser.add_argument("--offset", type=int, default=0, help="With --cards/--subtitles: first to show.")
    parser.add_argument("--limit", type=int, default=50, help="With --cards/--subtitles: how many.")
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
        "job_id": args.job_id,
        # Pass to patch_cards as --revision so an edit made against a stale read
        # is refused instead of overwriting someone else's change.
        "revision": editor.get("revision"),
        "run_status": status_row.get("status"),
        "source_language": status_row.get("sourceLanguage"),
        "target_languages": targets,
        "cards": {lang: card_summary(rows, lang) for lang in targets},
        # What the run was actually created with, read back rather than assumed.
        "settings": {
            "emotion_detection": bool((status_row.get("inputData") or {}).get("emotionDetection")),
            "multi_speaker": bool((status_row.get("inputData") or {}).get("multiSpeaker")),
        },
        "awaiting_voices": bool(status_row.get("awaitingHumanValidation")),
        # The run's progress in the webapp's steps, as the API reports it.
        "progress": _progress.dub_progress(status_row),
        "background_jobs": running_jobs(base, headers, args.job_id),
        "usage": usage(base, headers),
    }
    result["issues"] = {
        lang: counts for lang in targets
        if (counts := issue_counts(base, headers, args.job_id, lang)) is not None
    }
    saved = _common.load_manifest(args.job_id)
    if saved:
        result["checkpoint"] = str(_common.manifest_path(args.job_id))
        numbers = _cards.line_numbers(rows)
        result["audio_stale"] = {
            k: sorted(numbers[c] for c in v if c in numbers)
            for k, v in (saved.get("audio_stale") or {}).items() if v
        }
        result["exports"] = {
            lang: {k: e.get(k) for k in ("export_id", "revision", "resolution")}
            for lang, e in (saved.get("exports") or {}).items()
        }

    result["suggestions"] = suggest(result, args.job_id)
    first = result["suggestions"][0]["run"].split(".py")[0] if result["suggestions"] else None
    result["next_action"] = first or "list_issues"

    if args.cards:
        if args.cards not in targets:
            sys.stderr.write(
                f"[warn] '{args.cards}' is not a target language of this dub "
                f"({', '.join(targets) or 'none'})\n"
            )
        got = _cue.page(describe_cards(rows, args.cards), args.offset, args.limit, f"--cards {args.cards}")
        result["lines"] = {"language": args.cards, "total": got["total"], "items": got["items"]}
        if "more" in got:
            result["lines"]["more"] = got["more"]
    if args.subtitles:
        got = _cue.page(_cue.subtitle_lines(rows, args.subtitles), args.offset, args.limit,
                        f"--subtitles {args.subtitles}")
        result["subtitle_lines"] = {"language": args.subtitles, "total": got["total"], "items": got["items"]}
        if "more" in got:
            result["subtitle_lines"]["more"] = got["more"]

    print(json.dumps(result, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
