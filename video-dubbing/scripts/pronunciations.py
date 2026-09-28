#!/usr/bin/env python3
"""How the voices pronounce words: brand names, acronyms, people's names.

  list     [--language L]                            the rules in force
  add      --word SQL --say sequel --language L      organization-wide
           [--phoneme --alphabet ipa] [--case-sensitive]
           [--job-id J --line N]                     just that dub line instead
  remove   --word SQL --language L [--job-id J --line N]

  POST   /v1/pronunciation-dictionary/org-rules
  POST   /v1/pronunciation-dictionary/transcripts/pronunciation-overrides
  GET    /v1/pronunciation-dictionary/rules
  DELETE /v1/pronunciation-dictionary/rules/{id} | …/transcripts/pronunciation-overrides

A rule changes how NEW speech sounds: re-voice the lines that use the word
(regenerate_cards.py --lines …, or card_ops.py speak) for it to be heard.

Prints JSON: list → { "rules": [{"word", "say", "language", "scope", "how"}] };
add/remove → { "status": "added" | "removed", …, "next_action" }

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _cards  # noqa: E402
import _api  # noqa: E402
import _common  # noqa: E402

PD = "/v1/pronunciation-dictionary"
die = _common.die


def call(method: str, path: str, body: dict | None = None, what: str = "") -> object:
    return _api.call(method, PD + path, body if method == "POST" else None, what=what)


def rules(language: str | None, **scope) -> list[dict]:
    q = urlencode({k: v for k, v in {"language": language, **scope}.items() if v})
    payload = call("GET", f"/rules?{q}", what="list pronunciation rules")
    rows = payload if isinstance(payload, list) else (payload or {}).get("data") or []
    return [r for r in rows if isinstance(r, dict)]


def main() -> int:
    parser = argparse.ArgumentParser(description="Pronunciation rules for the voices.")
    parser.add_argument("action", choices=["list", "add", "remove"])
    parser.add_argument("--word", help="The word or phrase as written, e.g. SQL.")
    parser.add_argument("--say", help="How to say it, e.g. sequel (or IPA with --phoneme).")
    parser.add_argument("--language", help="Language key, e.g. hindi_india.")
    parser.add_argument("--phoneme", action="store_true", help="--say is phonetic notation, not a respelling.")
    parser.add_argument("--alphabet", default="ipa", help="With --phoneme: ipa (default) or cmu-arpabet.")
    parser.add_argument("--case-sensitive", action="store_true")
    parser.add_argument("--job-id", help="With --line: only this dub's line.")
    parser.add_argument("--line", type=int, help="The line number (inspect_process --cards).")
    args = parser.parse_args()

    if args.action == "list":
        found = rules(args.language)
        print(json.dumps({"rules": [{k: v for k, v in {
            "word": r.get("matchText"), "say": r.get("value"), "language": r.get("language"),
            "scope": {"organization": "organization", "transcript_segment": "one line",
                      "system": "built in"}.get(r.get("scope"), r.get("scope")),
            "how": "phoneme" if r.get("strategy") == "phoneme" else None}.items() if v}
            for r in found]}, ensure_ascii=False))
        return 0

    if not args.word or not args.language:
        die(_common.EXIT_API_ERROR, f"{args.action} needs --word and --language.")
    if bool(args.job_id) != bool(args.line):
        die(_common.EXIT_API_ERROR, "a line rule needs both --job-id and --line.")
    card = None
    if args.line:
        cards, _ = _cards.read_editor(_common.base_url(), _common.headers(), args.job_id)
        card = _cards.card_at_line(cards, args.line)

    if args.action == "add":
        if not args.say:
            die(_common.EXIT_API_ERROR, "add needs --say (how the word should sound).")
        rule = {"matchText": args.word, "strategy": "phoneme" if args.phoneme else "alias", "value": args.say,
                **({"alphabet": args.alphabet} if args.phoneme else {}),
                **({"caseSensitive": True} if args.case_sensitive else {})}
        if card:
            call("POST", "/transcripts/pronunciation-overrides", {
                "processId": args.job_id, "transcriptId": card, "language": args.language,
                "rule": {**rule, "enabled": True}}, what="save the line's pronunciation")
        else:
            call("POST", "/org-rules", {"language": args.language, **rule}, what="save the pronunciation")
        print(json.dumps({"status": "added", "word": args.word, "say": args.say, "language": args.language,
                          "scope": "one line" if card else "organization",
                          # New speech uses it; existing audio doesn't change until re-voiced.
                          "next_action": "regenerate_cards"}, ensure_ascii=False))
        return 0

    if card:
        match = next((r for r in rules(args.language, processId=args.job_id, transcriptId=card)
                      if r.get("matchText") == args.word), None)
        if not match:
            die(_common.EXIT_API_ERROR, f'line {args.line} has no rule for "{args.word}".')
        q = urlencode({"processId": args.job_id, "transcriptId": card, "language": args.language,
                       "matchText": args.word, "value": match.get("value")})
        call("DELETE", f"/transcripts/pronunciation-overrides?{q}", what="remove the line's pronunciation")
    else:
        match = next((r for r in rules(args.language) if r.get("matchText") == args.word
                      and r.get("scope") == "organization"), None)
        if not match:
            die(_common.EXIT_API_ERROR, f'there is no organization rule for "{args.word}" in {args.language}.')
        call("DELETE", f"/rules/{quote(str(match.get('id')))}", what="remove the pronunciation")
    print(json.dumps({"status": "removed", "word": args.word, "language": args.language,
                      "next_action": "regenerate_cards"}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
