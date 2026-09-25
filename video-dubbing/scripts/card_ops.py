#!/usr/bin/env python3
"""Card operations beyond field edits — everything else the editor does to a
card. Field edits (text, timing, emotion, rate, Keep Source, lip-sync, review
status, volume) are patch_cards.py.

  split          --card-id X --chunks '["first part", "second part"]'   (2-3)
  merge          --card-ids A,B[,C]         consecutive cards, same speaker
  delete         --card-id X
  add            --after X | --before X  --start S --end E  [--text "..."]
                 [--speaker-id N]           a new line in the gap next to X
  assign-speaker --card-id X --speaker-id N
  add-speaker    --card-id X --label "Name" --gender male|female
  speaker-voice  --speaker-id N --language L --voice-id V --voice-name "..."
                 [--voice-type T]           that speaker's voice in one language
  retranslate    --card-id X --language L   re-translate one line from the source
  speak          --card-id X --language L  [--voice-id V --voice-name "..."
                 --voice-type T]            re-voice ONE line now (optionally in
                                            another voice), synchronously
  sub-update     --card-id X --language L --subtitle-id S [--text] [--start --end]
  sub-delete     --card-id X --language L --subtitle-id S
  sub-split      --card-id X --language L --subtitle-id S --at-word N
  sub-merge      --card-id X --language L --subtitle-ids S1,S2

Structural and subtitle edits carry `expectedRevision` (from --revision or
read now) and are refused with 409 if the transcript changed meanwhile.
`retranslate` and `speak` are billed per use and are not revision-guarded (a
refusal after the work ran would charge for nothing).

What each one leaves to do next is in `next_action` / `follow_up`:
  split        -> the new cards have no translation or audio: retranslate +
                  speak (or regenerate_cards --missing) per target language
  merge        -> the merged card has no audio: regenerate_cards --missing
  add          -> empty line: patch_cards text (source), retranslate, speak
  speaker-voice-> that speaker's cards in L lose their audio: regenerate_cards
                  --missing
Prints JSON: { "status": "done", "operation", "revision_after", "cards": [...],
               "follow_up": "...", "next_action": "..." }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import secrets
import string
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _cards  # noqa: E402
import _common  # noqa: E402
import _http  # noqa: E402
import _voices  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
STATUS_PATH = PL + "/{job_id}/status"
TRANSCRIPT_ACTION = PL + "/transcript/action"
SUBTITLE_ACTION = PL + "/subtitle/action"
SYNC_ACTION = PL + "/sync-services/action"
ASSIGN_SPEAKER = PL + "/{job_id}/assign-speaker"
ADD_SPEAKER = PL + "/{job_id}/speakers"
SPEAKER_VOICE = PL + "/{job_id}/speaker-voice"

die = _common.die


def check(status: int, payload: object, what: str) -> None:
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, what))
    if status == 409:
        die(
            _common.EXIT_API_ERROR,
            f"{what} was not applied: the transcript changed meanwhile. Re-run "
            "inspect_process and try again.",
            error_code="REVISION_CONFLICT",
        )
    if status == 402 or (isinstance(payload, dict) and "credit" in str(payload.get("message", "")).lower()):
        die(_common.EXIT_API_ERROR, f"{what}: {_common.api_message(payload)}", error_code="INSUFFICIENT_CREDITS")
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR, f"{what} failed ({status}): {_common.api_message(payload)}")


def call(method: str, url: str, headers: dict, body: dict, what: str) -> object:
    try:
        fn = _http.put_json if method == "PUT" else _http.post_json
        status, payload = fn(url, headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error during {what}: {e}")
    check(status, payload, what)
    return payload


def guarded(base: str, headers: dict, job: str, path: str, action: str, data, revision, what: str):
    """An editor action with optional expectedRevision; returns (payload, revision)."""
    body: dict = {"id": job, "action": action, "data": data}
    if revision is not None:
        body["expectedRevision"] = revision
    payload = call("POST", base + path, headers, body, what)
    header = _http.last_headers.get("x-transcript-revision")
    return payload, (int(header) if header and header.isdigit() else None)


def new_card_id() -> str:
    alphabet = string.ascii_letters + string.digits + "_-"
    return "".join(secrets.choice(alphabet) for _ in range(5))


def status_row(base: str, headers: dict, job: str) -> dict:
    try:
        status, payload = _http.get_json(base + STATUS_PATH.format(job_id=job), headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the dub: {e}")
    check(status, payload, "reading the dub")
    return payload if isinstance(payload, dict) else {}


def card_or_die(index: dict, cid: str) -> dict:
    card = index.get(cid)
    if card is None:
        die(_common.EXIT_API_ERROR, f"card {cid} is not in this dub.")
    return card


def subtitle_or_die(card: dict, lang: str, sid: str) -> tuple[list, int]:
    subs = _cards.block(card, lang).get("subs")
    subs = subs if isinstance(subs, list) else []
    for i, sub in enumerate(subs):
        if isinstance(sub, dict) and sub.get("id") == sid:
            return subs, i
    die(_common.EXIT_API_ERROR, f"subtitle {sid} is not on card {card.get('id')} in {lang}.")
    return [], -1  # unreachable


def main() -> int:
    parser = argparse.ArgumentParser(description="Card operations (split, merge, speakers, voices, subtitles, ...).")
    parser.add_argument("operation", choices=[
        "split", "merge", "delete", "add", "assign-speaker", "add-speaker", "speaker-voice",
        "retranslate", "speak", "sub-update", "sub-delete", "sub-split", "sub-merge",
    ])
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--card-id")
    parser.add_argument("--card-ids")
    parser.add_argument("--language")
    parser.add_argument("--chunks", help='JSON list of 2-3 source-text pieces, in order.')
    parser.add_argument("--after")
    parser.add_argument("--before")
    parser.add_argument("--start", type=float)
    parser.add_argument("--end", type=float)
    parser.add_argument("--text")
    parser.add_argument("--speaker-id")
    parser.add_argument("--label")
    parser.add_argument("--gender", choices=["male", "female"])
    parser.add_argument("--voice-id")
    parser.add_argument("--voice-name")
    parser.add_argument("--voice-type")
    parser.add_argument("--subtitle-id")
    parser.add_argument("--subtitle-ids")
    parser.add_argument("--at-word", type=int)
    parser.add_argument("--revision", type=int, help="Revision from inspect_process; refuses if it moved.")
    args = parser.parse_args()

    def need(*names: str) -> None:
        missing = [n for n in names if getattr(args, n.replace("-", "_")) in (None, "")]
        if missing:
            die(_common.EXIT_API_ERROR, f"{args.operation} needs --" + ", --".join(missing))

    base = _common.base_url()
    headers = _common.headers()
    job = args.job_id
    op = args.operation

    cards, current = _cards.read_editor(base, headers, job)
    if args.revision is not None and current is not None and args.revision != current:
        die(_common.EXIT_API_ERROR,
            f"the transcript changed since it was inspected (revision {args.revision} -> {current}).",
            error_code="REVISION_CONFLICT", current_revision=current)
    revision = args.revision if args.revision is not None else current
    index = _cards.by_id(cards)
    row = status_row(base, headers, job)
    source = row.get("sourceLanguage") or ""
    targets = row.get("targetLanguages") or []

    result: dict = {"status": "done", "operation": op}
    follow_up, next_action = None, "inspect_process"

    if op == "split":
        need("card-id", "chunks")
        card = card_or_die(index, args.card_id)
        try:
            chunks = [c.strip() for c in json.loads(args.chunks) if isinstance(c, str) and c.strip()]
        except ValueError:
            chunks = []
        if not 2 <= len(chunks) <= 3:
            die(_common.EXIT_API_ERROR, "--chunks must be 2 or 3 non-empty pieces of the source line.")
        original = ((_cards.block(card, source).get("tr") or {}).get("text") or "")
        if " ".join(" ".join(chunks).split()) != " ".join(original.split()):
            die(_common.EXIT_API_ERROR,
                "the chunks must be the source line split up, word for word:\n" + original)
        payload, revision = guarded(base, headers, job, TRANSCRIPT_ACTION, "split",
                                    {"transcriptId": args.card_id, "chunks": chunks}, revision, "split")
        new_ids = [c.get("id") for c in (payload or {}).get("chunks") or [] if isinstance(c, dict)]
        result["cards"] = new_ids
        follow_up = ("The new cards have no translation or audio in "
                     + ", ".join(targets) + ": retranslate then speak each (or regenerate_cards --missing).")
        next_action = "retranslate"
        # The new cards have NO audio (a blocking issue), not stale audio.
        for t in targets:
            _common.prune_stale(job, t, lambda cid: cid not in new_ids)

    elif op == "merge":
        need("card-ids")
        ids = [x.strip() for x in args.card_ids.split(",") if x.strip()]
        for cid in ids:
            card_or_die(index, cid)
        payload, revision = guarded(base, headers, job, TRANSCRIPT_ACTION, "merge",
                                    {"transcriptIds": ids}, revision, "merge")
        result["cards"] = ids[:1]
        for t in targets:  # merged-away cards no longer exist
            _common.prune_stale(job, t, lambda cid: cid not in ids[1:])
        follow_up = "The merged card needs new audio in every language: regenerate_cards --missing."
        next_action = "regenerate_cards"

    elif op == "delete":
        need("card-id")
        card_or_die(index, args.card_id)
        _, revision = guarded(base, headers, job, TRANSCRIPT_ACTION, "delete",
                              {"transcriptId": args.card_id}, revision, "delete")
        result["cards"] = [args.card_id]

    elif op == "add":
        need("start", "end")
        anchor_id = args.after or args.before
        if not anchor_id:
            die(_common.EXIT_API_ERROR, "add needs --after or --before a card.")
        anchor = card_or_die(index, anchor_id)
        st, et = args.start, args.end
        if st < 0 or st >= et:
            die(_common.EXIT_API_ERROR, "--start must be before --end.")
        duration = _cards.video_duration()
        if duration and et > duration + 1e-6:
            die(_common.EXIT_API_ERROR, f"--end is past the end of the video ({duration}s).")
        prev, nxt = _cards.neighbours(cards, anchor_id, source)
        lo = ((_cards.block(anchor, source).get("v") or {}).get("et") if args.after
              else ((_cards.block(prev, source).get("v") or {}).get("et") if prev else 0))
        hi = (((_cards.block(nxt, source).get("v") or {}).get("st") if nxt else duration or None)
              if args.after else (_cards.block(anchor, source).get("v") or {}).get("st"))
        if (lo is not None and st < lo - 1e-6) or (hi is not None and et > hi + 1e-6):
            die(_common.EXIT_API_ERROR, f"the new line must fit in the gap {lo}s – {hi}s without overlapping.")
        speaker = args.speaker_id or (_cards.block(anchor, source).get("speakerId") or anchor.get("speakerId"))
        text = (args.text or "").strip()
        new_card: dict = {"id": new_card_id()}
        for lang in [k for k in anchor if k not in ("id", "ref", "isGap", "index", "merged")]:
            if not isinstance(anchor.get(lang), dict):
                continue
            new_card[lang] = {
                "tr": {"text": text if lang == source else "", "cc": len(text) if lang == source else 0,
                       "wc": len(text.split()) if lang == source else 0, "c": 0},
                "a": None, "v": {"st": st, "et": et, "r": 1}, "subs": [],
            }
        if source in new_card:
            new_card[source]["speakerId"] = speaker
            new_card[source]["tr"]["diarization"] = {"start": st, "end": et, "text": text}
        position = [str(c.get("id")) for c in cards].index(anchor_id) + (1 if args.after else 0)
        _, revision = guarded(base, headers, job, TRANSCRIPT_ACTION, "add",
                              {"transcript": new_card, "index": position}, revision, "add")
        result["cards"] = [new_card["id"]]
        follow_up = "Empty in every dubbed language: retranslate then speak it per language."
        next_action = "retranslate"

    elif op == "assign-speaker":
        need("card-id", "speaker-id")
        card_or_die(index, args.card_id)
        call("PUT", base + ASSIGN_SPEAKER.format(job_id=job), headers,
             {"transcriptId": args.card_id, "speakerId": str(args.speaker_id)}, "assign speaker")
        result["cards"] = [args.card_id]
        follow_up = "Its audio was made with the previous speaker's voice: speak it again per language."
        next_action = "speak"

    elif op == "add-speaker":
        need("card-id", "label", "gender")
        card_or_die(index, args.card_id)
        payload = call("POST", base + ADD_SPEAKER.format(job_id=job), headers,
                       {"label": args.label, "gender": args.gender, "transcriptId": args.card_id}, "add speaker")
        result["speaker_id"] = (payload or {}).get("speakerId")
        result["cards"] = [args.card_id]
        follow_up = "Give the new speaker a voice per language (speaker-voice), then speak the card."
        next_action = "speaker-voice"

    elif op == "speaker-voice":
        need("speaker-id", "language", "voice-id", "voice-name")
        body = {"speakerId": str(args.speaker_id), "targetLanguage": args.language,
                "voiceId": args.voice_id, "voiceName": args.voice_name}
        if args.voice_type:
            body["voiceType"] = args.voice_type
        payload = call("PUT", base + SPEAKER_VOICE.format(job_id=job), headers, body, "change the speaker's voice")
        cleared = [c.get("id") for c in (payload or {}).get("updatedTranscripts") or [] if isinstance(c, dict)]
        result["cards"] = cleared
        _common.update_manifest(job, voice_map={str(args.speaker_id): {
            **((_common.load_manifest(job).get("voice_map") or {}).get(str(args.speaker_id)) or {}),
            args.language: args.voice_id}})
        follow_up = f"{len(cleared)} card(s) of this speaker lost their audio in {args.language}: regenerate_cards --missing."
        next_action = "regenerate_cards"

    elif op in ("retranslate", "speak"):
        need("card-id", "language")
        card = card_or_die(index, args.card_id)
        if args.language not in targets:
            die(_common.EXIT_API_ERROR, f"{args.language} is not a dubbed language of this dub.")
        if op == "retranslate":
            data = {"transcriptId": args.card_id, "targetLanguage": args.language}
            call("POST", base + SYNC_ACTION, headers, {"id": job, "action": "text-translation", "data": data},
                 "re-translate the line")
            follow_up = "The line has new text and no audio yet: speak it."
            next_action = "speak"
        else:
            data = {"transcriptId": args.card_id, "language": args.language}
            clones = _voices.list_cloned(base, headers)
            if args.voice_id:
                voice = _voices.as_voice(args.voice_id, clones, args.voice_name or "")
                if args.voice_type:
                    voice["voiceType"] = args.voice_type
                data["voice"] = voice
            else:
                # The speaker's own voice for this language — typed, so a saved
                # clone is not looked up as a catalog voice.
                speaker = str(_cards.block(card, source).get("speakerId") or card.get("speakerId") or "")
                profile = (((row.get("inputData") or {}).get("speakers") or {}).get(speaker) or {}).get(args.language) or {}
                if profile.get("voiceId") and not profile.get("voiceType"):
                    data["voice"] = _voices.as_voice(profile["voiceId"], clones, profile.get("voiceName") or "")
            before = _cards.fingerprint(card, args.language)
            call("POST", base + SYNC_ACTION, headers, {"id": job, "action": "text-to-speech", "data": data},
                 "voice the line")
            after_cards, revision = _cards.read_editor(base, headers, job)
            after = _cards.fingerprint(_cards.by_id(after_cards).get(args.card_id, {}), args.language)
            result["audio"] = {"has_audio": bool(after), "duration_seconds": after.get("duration_seconds"),
                               "audio_sha256": after.get("sha256"),
                               "changed": bool(after) and after.get("sha256") != before.get("sha256")}
            saved = _common.load_manifest(job)
            stale = [c for c in ((saved.get("audio_stale") or {}).get(args.language) or []) if c != args.card_id]
            _common.update_manifest(job, audio_stale={args.language: stale})
            next_action = "list_issues"
        result["cards"] = [args.card_id]
        if op == "retranslate":
            revision = _cards.read_editor(base, headers, job)[1]

    else:  # subtitle lines
        need("card-id", "language")
        card = card_or_die(index, args.card_id)
        path = {"language": args.language, "transcriptId": args.card_id}
        if op == "sub-update":
            need("subtitle-id")
            subs, i = subtitle_or_die(card, args.language, args.subtitle_id)
            sub = dict(subs[i])
            if args.text is not None:
                sub["text"] = args.text.strip()
            if args.start is not None or args.end is not None:
                t = dict(sub.get("t") or {})
                t["st"] = args.start if args.start is not None else t.get("st")
                t["et"] = args.end if args.end is not None else t.get("et")
                if t["st"] is None or t["et"] is None or t["st"] >= t["et"]:
                    die(_common.EXIT_API_ERROR, "subtitle start must be before its end.")
                sub["t"] = t
            data = {"path": {**path, "subtitleId": args.subtitle_id}, "subtitle": sub}
            _, revision = guarded(base, headers, job, SUBTITLE_ACTION, "updateById", data, revision, "update subtitle")
        elif op == "sub-delete":
            need("subtitle-id")
            subtitle_or_die(card, args.language, args.subtitle_id)
            _, revision = guarded(base, headers, job, SUBTITLE_ACTION, "delete",
                                  {"path": {**path, "subtitleId": args.subtitle_id}}, revision, "delete subtitle")
        elif op == "sub-split":
            need("subtitle-id", "at-word")
            subs, i = subtitle_or_die(card, args.language, args.subtitle_id)
            sub = subs[i]
            words = str(sub.get("text") or "").split()
            if not 0 < args.at_word < len(words):
                die(_common.EXIT_API_ERROR, f"--at-word must be between 1 and {len(words) - 1}.")
            st, et = (sub.get("t") or {}).get("st", 0), (sub.get("t") or {}).get("et", 0)
            cut = st + (et - st) * args.at_word / len(words)
            parts = [
                {"id": sub["id"], "t": {"st": st, "et": cut}, "text": " ".join(words[:args.at_word])},
                {"id": new_card_id(), "t": {"st": cut, "et": et}, "text": " ".join(words[args.at_word:])},
            ]
            _, revision = guarded(base, headers, job, SUBTITLE_ACTION, "split",
                                  {"path": {**path, "subtitleId": args.subtitle_id}, "subtitles": parts},
                                  revision, "split subtitle")
        elif op == "sub-merge":
            need("subtitle-ids")
            ids = [x.strip() for x in args.subtitle_ids.split(",") if x.strip()]
            picked = []
            for sid in ids:
                subs, i = subtitle_or_die(card, args.language, sid)
                picked.append((i, subs[i]))
            picked.sort()
            if len(picked) < 2 or any(b[0] != a[0] + 1 for a, b in zip(picked, picked[1:])):
                die(_common.EXIT_API_ERROR, "sub-merge needs 2+ consecutive subtitle lines.")
            first, last = picked[0][1], picked[-1][1]
            merged = {"id": first["id"],
                      "t": {"st": (first.get("t") or {}).get("st"), "et": (last.get("t") or {}).get("et")},
                      "text": " ".join(str(s.get("text") or "").strip() for _, s in picked)}
            _, revision = guarded(base, headers, job, SUBTITLE_ACTION, "merge",
                                  {"path": path, "subtitleIds": ids, "merged": merged}, revision, "merge subtitles")
        result["cards"] = [args.card_id]

    if revision is None and op not in ("retranslate", "speak"):
        revision = _cards.read_editor(base, headers, job)[1]
    _common.update_manifest(job, revision=revision)
    result.update({"revision_after": revision, "follow_up": follow_up, "next_action": next_action})
    print(json.dumps(result))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
