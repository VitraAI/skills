#!/usr/bin/env python3
"""Score one language of a translated DITA map phrase by phrase (accuracy,
fluency, terminology, style) and, if the user wants, write the suggested fixes
into the map and rebuild its zip.

  POST .../dita-map/qe-report/publish     { playgroundLogId, scope }
  GET  /v1/aiqe/reports/{id}              until finished
  PUT  .../dita-map/qe-report/apply-fix   { playgroundLogId, reportId, keys }  — --apply-fixes
  POST .../dita-map/{run}/generate-translation-zip, then the zip   — --out

Issues are numbered 1, 2, … in the order shown; --apply-fixes takes those
numbers (or "all") and uses the last report run for this translation.

Prints JSON: { "status": "scored", "score", "band", "passed", "lines_with_errors",
               "worst": [{"issue", "file", "source", "translation", "score",
                          "errors", "better"}] }
  or, with --apply-fixes: { "status": "fixed", "applied", "unchanged", "skipped", "path"? }

Spends credits per source word. Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _aiqe  # noqa: E402
import _common  # noqa: E402
import _dita  # noqa: E402
import _state  # noqa: E402

die = _common.die


def apply(run: str, which: str, out: str | None) -> dict:
    last = _state.recall("dita-translation", f"qe:{run}")
    body: dict = {"playgroundLogId": run}
    if which.strip().lower() != "all":
        if not last:
            die(_common.EXIT_API_ERROR, "run the quality report first; fixes are chosen from its issues.")
        try:
            wanted = [int(x) for x in which.split(",") if x.strip()]
        except ValueError:
            die(_common.EXIT_API_ERROR, 'issues are numbers from the report, e.g. "1,3", or "all".')
        keys = last["keys"]
        if any(n < 1 or n > len(keys) for n in wanted):
            die(_common.EXIT_API_ERROR, f"the last report listed issues 1 to {len(keys)}.")
        body["keys"] = [keys[n - 1] for n in wanted]
    if last:
        body["reportId"] = last["report"]
    got = _dita.call("PUT", "/qe-report/apply-fix", body, what="apply the fixes")
    got = got.get("data") if isinstance(got.get("data"), dict) else got
    result = {"status": "fixed", "applied": got.get("applied"), "unchanged": got.get("unchanged"),
              "skipped": got.get("skipped")}
    if got.get("skipped"):
        result["note"] = "skipped fixes would have broken the topic's markup; they were left as they are"
    if not out:  # translate_dita.py rebuilds the zip on its next run
        _state.remember("dita-translation", f"stale:{run}", {"stale": True})
        result["next_action"] = "rebuild the zip: run translate_dita.py again, or pass --out here"
    else:
        built = _dita.build_zip(run, allow_partial=True)
        if built.get("refused"):
            die(_common.EXIT_API_ERROR, f"the fixes were applied but the zip was not rebuilt: {built['refused']}")
        result["path"] = _dita.download(built["url"], Path(out).expanduser())
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Score a DITA map translation; apply fixes.")
    parser.add_argument("--translation", required=True, help="One language's `translation` from translate_dita.py.")
    parser.add_argument("--scope", choices=["all", "unverified"], default="all")
    parser.add_argument("--apply-fixes", metavar="ISSUES|all", help='"all", or issue numbers like "1,3".')
    parser.add_argument("--out", help="With --apply-fixes: rebuild the translated zip and save it here.")
    parser.add_argument("--show", type=int, default=10)
    parser.add_argument("--max-wait", type=int, default=1800)
    args = parser.parse_args()
    run = args.translation

    if args.apply_fixes:
        print(json.dumps(apply(run, args.apply_fixes, args.out), ensure_ascii=False))
        return _common.EXIT_OK

    started = _dita.call("POST", "/qe-report/publish", {"playgroundLogId": run, "scope": args.scope},
                         what="start the report")
    started = started.get("data") if isinstance(started.get("data"), dict) else started
    report = started.get("report") or {}
    if not report.get("id"):
        die(_common.EXIT_API_ERROR, "Vitra did not start the report.")
    base, headers = _common.base_url(), _common.headers()
    report = _aiqe.wait(base, headers, report, args.max_wait)

    paths = {f["row"]: f["path"] for f in _dita.topics(_dita.status(run).get("tree") or [])}
    keys: list[str] = []

    def label(key: str) -> dict:  # "<topic row>:<phrase>" → the topic's path
        keys.append(key)
        return {"issue": len(keys), "file": paths.get(key.split(":", 1)[0], "a topic")}

    _, worst = _aiqe.worst_lines(base, headers, str(report["id"]), args.show, label=label)
    _state.remember("dita-translation", f"qe:{run}", {"report": str(report["id"]), "keys": keys})
    print(json.dumps({"status": "scored", **_aiqe.summary(report), "worst": worst,
                      "next_action": "quality_report --apply-fixes" if worst else None}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
