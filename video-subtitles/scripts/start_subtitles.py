#!/usr/bin/env python3
"""Start subtitles: from a video (transcribe) or from a subtitle file (translate).

The mode follows the file, as in the webapp:
  video (.mp4, .mov, …)           -> subtitle generation (VIDEO_TO_SUBTITLE):
                                     subtitles in the spoken language. Add
                                     translated languages afterwards with
                                     add_subtitle_language.py, once reviewed.
  subtitle file (.srt .vtt .ass .ssa) -> subtitle translation
                                     (SUBTITLE_TO_TRANSCRIPT_TRANSLATION) into
                                     every --target-language.

  --script (video only): a script of what is said (.srt .vtt .ass .ssa .txt);
  transcription follows it, and a timed script's cues are kept 1:1.

  POST /v1/galaxy/translate-video/upload         (or reuse an identical upload)
  POST /v1/galaxy/translate-video/process-log/publish   (idempotent)
  GET  .../process-log/{id}/status               until ready

Prints JSON:
  { "status": "review_ready" | "failed", "job_id", "mode", "source_language",
    "target_languages", "progress", "next_action": "inspect_subtitles" }

Re-running it for the same file and languages reconnects to the same job.

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
import _progress  # noqa: E402
import _tm  # noqa: E402
import _tv  # noqa: E402

# Subtitle file types the API accepts.
SUBTITLE_EXTENSIONS = {".srt", ".vtt", ".ass", ".ssa"}
SCRIPT_EXTENSIONS = SUBTITLE_EXTENSIONS | {".txt"}
GENERATE, TRANSLATE = "VIDEO_TO_SUBTITLE", "SUBTITLE_TO_TRANSCRIPT_TRANSLATION"
DEFAULT_MAX_WAIT = 1800

die = _common.die


def choose_memory(base: str, headers: dict, args, targets: list[str]) -> tuple[str, str]:
    """The memory for a subtitle generation job (the server requires one).

    It is also the memory later languages are translated with, so it is the
    user's choice: one available → use it; several → ask; none → create one
    from the user's answers.
    """
    tms = _tm.list_tms(base, headers)
    if args.create_tm:
        if not targets or not (args.tm_context or "").strip():
            die(_common.EXIT_API_ERROR,
                "creating a memory needs the languages the subtitles will be translated "
                "into (--target-language) and one sentence on who it is for (--tm-context).",
                error_code="TM_CONTEXT_NEEDED",
                ask="Which languages will you want these subtitles in, and who is this "
                    "memory for (the client or product, and the audience)?")
        name = f"dub · {args.source_language} → {', '.join(targets)}"
        existing = next((t for t in tms if t.get("name") == name and t.get("id")), None)
        if existing:
            return str(existing["id"]), name
        tm_id, reason = _tm.create_tm(base, headers, name, args.source_language, targets,
                                      args.tm_context, args.tm_engine)
        if not tm_id:
            die(_common.EXIT_API_ERROR, f"could not create the translation memory ({reason}).")
        sys.stderr.write(f"[memory] created “{name}”\n")
        return tm_id, name
    usable = [t for t in tms if t.get("id")]
    if len(usable) == 1:
        sys.stderr.write(f"[memory] using the only one: “{usable[0].get('name')}”\n")
        return str(usable[0]["id"]), usable[0].get("name") or ""
    if usable:
        die(_common.EXIT_API_ERROR,
            "this organization has several translation memories; the user must choose one.",
            error_code="TM_CHOICE_NEEDED",
            ask="Which translation memory should these subtitles use?",
            choices=[t.get("name") for t in usable])
    die(_common.EXIT_API_ERROR,
        "this organization has no translation memory yet, and subtitles need one.",
        error_code="TM_NEEDED",
        ask="Which languages will you want these subtitles in, and who is this memory "
            "for (the client or product, and the audience)? I'll create it.")
    return "", ""  # unreachable


def main() -> int:
    parser = argparse.ArgumentParser(description="Start subtitles from a video or a subtitle file.")
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="A video, or a subtitle file (.srt .vtt .ass .ssa).")
    src.add_argument("--url", help="Public http(s) URL of the same (downloaded, then uploaded).")
    parser.add_argument("--source-language", required=True, metavar="KEY",
                        help="Language spoken in the video / written in the file (list_languages.py).")
    parser.add_argument("--target-language", action="append", default=[], metavar="KEY",
                        help="Language to translate a subtitle FILE into (repeatable).")
    parser.add_argument("--tm-name", help="Translation memory to use, by the name list_tms.py shows.")
    parser.add_argument("--create-tm", action="store_true",
                        help="Create a memory for this job (needs --target-language and --tm-context).")
    parser.add_argument("--tm-context",
                        help="With --create-tm: one sentence on who the memory is for. Ask the user.")
    parser.add_argument("--tm-engine", choices=["gemini", "azure"],
                        help="With --create-tm: gemini (default, follows the style guide) or azure.")
    parser.add_argument("--script", help="With a video: its script (.srt .vtt .ass .ssa .txt), optional.")
    parser.add_argument("--name", help="Name shown in Vitra. Defaults to the file name.")
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    path, is_temp = _tv.resolve_source(args.file, args.url)
    mode = TRANSLATE if path.suffix.lower() in SUBTITLE_EXTENSIONS else GENERATE
    targets = sorted(set(args.target_language))
    if mode == TRANSLATE and not targets:
        die(_common.EXIT_API_ERROR, "a subtitle file needs at least one --target-language.",
            error_code="TARGET_LANGUAGE_NEEDED",
            ask="Which language(s) should these subtitles be translated into?")
    if mode == GENERATE and targets:
        # The webapp generates first, then adds languages from the reviewed
        # source; publishing a video with targets is not a subtitle job.
        sys.stderr.write("[subtitles] a video is transcribed first; add "
                         f"{', '.join(targets)} with add_subtitle_language.py after review\n")
    script = Path(args.script).expanduser() if args.script else None
    if script and mode == TRANSLATE:
        die(_common.EXIT_API_ERROR, "--script is for a video; a subtitle file is translated as it is.")
    if script and (not script.is_file() or script.suffix.lower() not in SCRIPT_EXTENSIONS):
        die(_common.EXIT_API_ERROR,
            f"--script must be an existing {', '.join(sorted(SCRIPT_EXTENSIONS))} file.")
    if args.source_language in targets:
        die(_common.EXIT_API_ERROR, "a target language can't be the source language.")

    base, headers = _common.base_url(), _common.headers()
    tm_id, memory = None, args.tm_name
    if args.tm_name:
        tm_id = _tm.resolve_by_name(base, headers, args.tm_name)
    elif mode == GENERATE:
        tm_id, memory = choose_memory(base, headers, args, targets)
    # Translating a file without --tm-name: the server finds or creates the
    # memory for this language pair, as for a dub.

    try:
        upload_id, sha = _tv.upload(base, headers, path)
    finally:
        if is_temp:
            path.unlink(missing_ok=True)
    # The server marks a subtitle/text upload beside a video as its script.
    script_id, script_sha = _tv.upload(base, headers, script) if script else (None, None)

    run_name = args.name or path.stem
    body = {
        "processType": mode,
        "processName": run_name,
        "uploadIds": [upload_id, *([script_id] if script_id else [])],
        "sourceLanguage": args.source_language,
        "metadata": {"source": "skill:video-subtitles"},
        "inputData": {
            "translationMode": "subtitle-translation" if mode == TRANSLATE else "subtitle-generation",
            "multiSpeaker": True,
            "speakerCount": "auto-detect",
            "compress": True,
        },
    }
    if mode == TRANSLATE:
        body["targetLanguages"] = targets
    if tm_id:
        body["tmId"] = tm_id
    key = _common.idempotency_key("subtitles", sha, mode, args.source_language, targets, tm_id, run_name,
                                  *([script_sha] if script_sha else []))
    job_id = _tv.publish(base, headers, body, key)
    sys.stderr.write("[subtitles] started\n")

    row = _tv.wait(base, headers, job_id, args.max_wait)
    progress = _progress.run_progress(row)
    state = str(row.get("status") or "").lower()
    if state != "completed":
        print(json.dumps({
            "status": "failed", "job_id": job_id, "mode": mode,
            "error": row.get("errorMessage") or f"the job {state}",
            "progress": progress, "next_action": "retry_subtitles",
        }))
        return _common.EXIT_API_ERROR

    print(json.dumps({
        "status": "review_ready",
        "job_id": job_id,
        "mode": "generate" if mode == GENERATE else "translate",
        "source_language": row.get("sourceLanguage") or args.source_language,
        "target_languages": row.get("targetLanguages") or [],
        "memory": memory,
        "progress": progress,
        "next_action": "inspect_subtitles",
    }))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
