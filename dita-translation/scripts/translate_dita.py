#!/usr/bin/env python3
"""Translate a DITA map (a .zip of topics, maps and SVGs) into one or more
languages and save one translated zip per language, structure and markup kept.

  POST .../dita-map/initialize                    multipart `file` + languages, memory
  GET  .../dita-map/{run}/files                   until every topic settled
  POST .../dita-map/{run}/retry                   with --retry-failed
  POST .../dita-map/{run}/generate-translation-zip, then the zip itself

Re-running the same command reconnects to the translation it started; add
--retry-failed to translate failed topics again, or --allow-partial to build
the zip with the original text for them.

Prints JSON: { "status": "translated" | "partial" | "failed", "memory", "words",
               "languages": [{"language", "translation", "topics", "path"?,
                              "failed": [{"file", "why"}]?}], "next_action"? }

Spends credits per word per language. Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import re
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _dita  # noqa: E402
import _http  # noqa: E402
import _state  # noqa: E402
import _tm  # noqa: E402

MAX_BYTES = 500 * 1024 * 1024
die = _common.die


def start(base: str, headers: dict, zip_path: Path, tm: dict, targets: list[str], name: str | None) -> dict:
    fields = {"sourceLanguage": tm.get("sourceLanguage"), "targetLanguages": json.dumps(targets),
              "tmId": str(tm["id"]), **({"name": name} if name else {})}
    try:
        status, payload = _http.post_multipart_json(base + _dita.DITA + "/initialize", headers, "file",
                                                    zip_path, fields, timeout=1800)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error uploading the map: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "translate DITA maps"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    data = payload.get("data") if isinstance(payload, dict) and isinstance(payload.get("data"), dict) else {}
    runs = data.get("playgroundLogIds") or []
    langs = data.get("targetLanguages") or targets
    if status not in (200, 201, 202) or len(runs) != len(langs):
        die(_common.EXIT_API_ERROR, f"the map did not start ({status}): {_common.api_message(payload)}")
    return {"runs": dict(zip(langs, (str(r) for r in runs))), "words": data.get("wordCount")}


def main() -> int:
    parser = argparse.ArgumentParser(description="Translate a DITA map zip.")
    parser.add_argument("--file", required=True, help="The DITA map as a .zip (up to 500 MB).")
    parser.add_argument("--target-language", action="append", required=True, metavar="LANGUAGE")
    parser.add_argument("--tm-name")
    parser.add_argument("--name", help="The map's name in Vitra (default: the file name).")
    parser.add_argument("--out-dir", default="translated")
    parser.add_argument("--retry-failed", action="store_true", help="Translate failed topics again first.")
    parser.add_argument("--allow-partial", action="store_true",
                        help="Build the zip even if some topics failed (their original text is kept).")
    parser.add_argument("--max-wait", type=int, default=3600)
    args = parser.parse_args()

    zip_path = Path(args.file).expanduser()
    if not zip_path.is_file():
        die(_common.EXIT_DOWNLOAD, f"--file not found: {zip_path}")
    if zip_path.suffix.lower() != ".zip":
        die(_common.EXIT_API_ERROR, "a DITA map is sent as one .zip of its maps, topics and images.")
    if zip_path.stat().st_size > MAX_BYTES:
        die(_common.EXIT_API_ERROR, "the zip is over 500 MB; split the map into smaller ones.")

    base, headers = _common.base_url(), _common.headers()
    tm = _tm.choose(base, headers, args.target_language[0], args.tm_name)
    targets = list(dict.fromkeys(_tm.target_in(tm, t, base, headers) for t in args.target_language))
    key = _common.idempotency_key("dita", _common.sha256_file(zip_path), sorted(targets), tm.get("id"))
    job = _state.recall("dita-translation", key)
    if not job:
        job = start(base, headers, zip_path, tm, targets, args.name)
        _state.remember("dita-translation", key, job)
    runs: dict[str, str] = job["runs"]

    if args.retry_failed:
        for lang, run in runs.items():
            s = _dita.status(run)
            if (s.get("summary") or {}).get("failed"):
                sys.stderr.write(f"[{lang}] translating failed topics again\n")
                _dita.call("POST", f"/{quote(run)}/retry", what="retry the failed topics", timeout=3600)

    states = _dita.wait(runs, args.max_wait)
    stem = re.sub(r"[^A-Za-z0-9_-]+", "_", args.name or zip_path.stem)
    out, blocked = [], []
    for lang, run in runs.items():
        s = states[lang]
        files = _dita.topics(s.get("tree") or [])
        failed = [{"file": f["path"], "why": f["error"] or "translation failed"}
                  for f in files if f["status"].upper() == "FAILED"]
        row: dict = {"language": lang, "translation": run, "topics": (s.get("summary") or {}).get("total")}
        prev = (job.get("built") or {}).get(lang)
        stale = _state.recall("dita-translation", f"stale:{run}")  # fixes were applied since
        if prev and Path(prev).is_file() and not (stale or args.retry_failed):
            row["path"] = prev  # already built: a rebuild would add a second copy to the Drive
        elif failed and not args.allow_partial:
            blocked.append(lang)
        else:
            built = _dita.build_zip(run, args.allow_partial)
            if built.get("refused"):
                row["error"] = built["refused"]
            else:
                dest = Path(args.out_dir) / f"{stem}-{re.sub(r'[^A-Za-z0-9_-]+', '_', lang)}.zip"
                row["path"] = _dita.download(built["url"], dest.expanduser())
                job.setdefault("built", {})[lang] = row["path"]
                _state.remember("dita-translation", key, job)
                _state.forget("dita-translation", f"stale:{run}")
        if failed:
            row["failed"] = failed[:20]
            if len(failed) > 20:
                row["more_failed"] = len(failed) - 20
        out.append(row)

    saved = [r for r in out if r.get("path")]
    status = "translated" if len(saved) == len(out) and not any(r.get("failed") for r in out) else (
        "partial" if saved or blocked else "failed")
    result: dict = {"status": status, "memory": tm.get("name"), "words": job.get("words"), "languages": out}
    if blocked:
        result["error"] = {"code": "TOPICS_FAILED", "ask": (
            f"Some topics failed in {', '.join(blocked)}. Translate them again (--retry-failed), or build "
            "the zip now with their original text (--allow-partial)?")}
        result["next_action"] = "ask_user"
    print(json.dumps(result, ensure_ascii=False))
    return _common.EXIT_OK if status == "translated" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
