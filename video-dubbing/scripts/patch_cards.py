#!/usr/bin/env python3
"""Change specific cards in ONE language: text, timing, emotion, rate, Keep
Source, lip-sync, review status, volume — the same edits the editor makes,
through the same actions. (Splitting, merging, adding or deleting cards,
speakers, voices and subtitle lines: card_ops.py.)

  GET  .../process-log/{jobId}/status          which languages exist
  GET  .../process-log/{jobId}/editor-output?includeRevision=true
  POST .../process-log/transcript/action  (one call per kind of change)
       update            { data: [{ id, <lang>: { tr, v } }] }   text, start/end
       updateReviewStatus{ ... status }          u unverified / v verified / a approved
       updateEmotion     { updateType:"selected", language, transcriptIds, emotion }
       updateRate        { ... rate }            0.5 – 2.0, applied at playback
       updateKeepSource  { ... enabled }         play the original audio instead
       updateLipSync     { ... enabled }
     each with expectedRevision
       saveAudio         { transcriptId, language, volume }   0.0 – 1.0

Timing: start/end (seconds) must stay inside the video and must not overlap
the neighbouring lines — checked here before anything is sent. A line whose
slot changes keeps its audio; re-run list_issues, since its rate may now be
out of range (fix_issues / a rate edit handles that).

Every edit is validated before anything is sent, so a bad value in the batch
changes nothing. Each call carries `expectedRevision`: if anyone else changed
the transcript meanwhile the server refuses (409) and the edit is not applied
over their work. The server returns the new revision (X-Transcript-Revision)
so the calls chain without re-reading the whole document.

The SOURCE language can be edited too (text only) — correct the transcript
before adding languages. Existing translations were made from the old text;
they are listed under `affected_languages` for review.

Text is sent WHOLE: the server merges a language block one level deep, so
`tr` goes as the card's current `tr` with only the text (and counts) changed.

Changing a dubbed line's TEXT removes its audio on the server (it would speak
the old sentence): those cards are listed under `audio_cleared` — run
`regenerate_cards.py --missing`. Changing EMOTION keeps the old clip: those
cards are listed under `audio_stale` (and saved to the run manifest) — run
`regenerate_cards.py --stale`. Rate, timing, Keep Source, lip-sync, review
status and volume need no regeneration.

--edits: JSON list of
  { "card_id": "...", "text"?: "...", "start"?: 12.3, "end"?: 15.0,
    "emotion"?: "calm", "rate"?: 1.1, "keep_source"?: true, "lip_sync"?: false,
    "review_status"?: "a", "volume"?: 0.8 }
(or the short form {"<cardId>": "new text"}).

Prints JSON:
  { "status": "patched" | "dry_run" | "unchanged", "language",
    "revision_before", "revision_after", "changes": [{card_id, field, before, after}],
    "audio_cleared": [...], "audio_stale": [...], "affected_languages": [...],
    "next_action": ... }

Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
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
import _http  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
STATUS_PATH = PL + "/{job_id}/status"
ACTION_PATH = PL + "/transcript/action"

# The server's emotion vocabulary (ELEVENLABS_EMOTION_TAGS).
EMOTIONS = {
    "neutral", "happy", "excited", "calm", "sad", "angry", "frustrated", "anxious",
    "surprised", "playful", "confident", "hesitant", "tired", "mysterious",
    "affectionate", "sarcastic", "curious", "disappointed", "confused",
}
MIN_RATE, MAX_RATE = 0.5, 2.0

# field -> (server action, value key, card-block reader)
TOGGLES = {
    "emotion": ("updateEmotion", "emotion", lambda b: b.get("emotion")),
    "rate": ("updateRate", "rate", lambda b: (b.get("a") or {}).get("r")),
    "keep_source": ("updateKeepSource", "enabled", lambda b: bool(b.get("keepSourceAudio"))),
    "lip_sync": ("updateLipSync", "enabled", lambda b: bool(b.get("isLipSync"))),
    "review_status": ("updateReviewStatus", "status", lambda b: b.get("rs") or "u"),
}
REVIEW_STATUSES = {"u", "v", "a"}
STALE_FIELDS = {"text", "emotion"}

die = _common.die


def parse_edits(raw: str) -> list[dict]:
    try:
        edits = json.loads(raw)
    except ValueError:
        die(_common.EXIT_API_ERROR, "--edits must be JSON")
    if isinstance(edits, dict):
        edits = [{"card_id": k, "text": v} for k, v in edits.items()]
    if not isinstance(edits, list) or not edits:
        die(_common.EXIT_API_ERROR, "--edits must be a non-empty list of edits")
    out = []
    for e in edits:
        if not isinstance(e, dict) or not e.get("card_id"):
            die(_common.EXIT_API_ERROR, f"each edit needs a card_id: {e!r}")
        edit = {"card_id": str(e["card_id"])}
        if "text" in e:
            if not isinstance(e["text"], str) or not e["text"].strip():
                die(_common.EXIT_API_ERROR, f"card {edit['card_id']}: text must be non-empty")
            edit["text"] = e["text"].strip()
        if "emotion" in e:
            if e["emotion"] not in EMOTIONS:
                die(_common.EXIT_API_ERROR,
                    f"card {edit['card_id']}: emotion must be one of {', '.join(sorted(EMOTIONS))}")
            edit["emotion"] = e["emotion"]
        if "rate" in e:
            try:
                rate = float(e["rate"])
            except (TypeError, ValueError):
                rate = -1
            if not MIN_RATE <= rate <= MAX_RATE:
                die(_common.EXIT_API_ERROR,
                    f"card {edit['card_id']}: rate must be between {MIN_RATE} and {MAX_RATE}")
            edit["rate"] = rate
        for field in ("start", "end"):
            if field in e:
                if not isinstance(e[field], (int, float)) or isinstance(e[field], bool) or e[field] < 0:
                    die(_common.EXIT_API_ERROR, f"card {edit['card_id']}: {field} must be seconds >= 0")
                edit[field] = float(e[field])
        if "review_status" in e:
            if e["review_status"] not in REVIEW_STATUSES:
                die(_common.EXIT_API_ERROR,
                    f"card {edit['card_id']}: review_status must be u (unverified), v (verified) or a (approved)")
            edit["review_status"] = e["review_status"]
        if "volume" in e:
            try:
                volume = float(e["volume"])
            except (TypeError, ValueError):
                volume = -1
            if not 0.0 <= volume <= 1.0:
                die(_common.EXIT_API_ERROR, f"card {edit['card_id']}: volume must be between 0 and 1")
            edit["volume"] = volume
        for flag in ("keep_source", "lip_sync"):
            if flag in e:
                if not isinstance(e[flag], bool):
                    die(_common.EXIT_API_ERROR, f"card {edit['card_id']}: {flag} must be true or false")
                edit[flag] = e[flag]
        if len(edit) == 1:
            die(_common.EXIT_API_ERROR, f"card {edit['card_id']}: nothing to change")
        out.append(edit)
    return out


def with_text(tr: dict, text: str) -> dict:
    """The card's whole `tr` with new text; counts kept in step if present."""
    new = dict(tr)
    new["text"] = text
    if "cc" in new:
        new["cc"] = len(text)
    if "wc" in new:
        new["wc"] = len(text.split())
    return new


def get_status(base: str, headers: dict, job_id: str) -> dict:
    try:
        status, payload = _http.get_json(base + STATUS_PATH.format(job_id=job_id), headers=headers)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the dub: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this dub"))
    if status != 200:
        die(_common.EXIT_API_ERROR, f"could not read the dub ({status}): {_common.api_message(payload)}")
    return payload if isinstance(payload, dict) else {}


def send(base: str, headers: dict, job_id: str, action: str, data, revision: int | None) -> int | None:
    """Run one action; return the revision after it (None if unknown)."""
    body: dict = {"id": job_id, "action": action, "data": data}
    if revision is not None:
        body["expectedRevision"] = revision
    try:
        status, payload = _http.post_json(base + ACTION_PATH, headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error saving the edit ({action}): {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "edit this transcript"))
    if status == 409:
        die(
            _common.EXIT_API_ERROR,
            "someone changed the transcript while this edit was being made; this "
            f"change ({action}) was not saved. Re-run inspect_process and redo the edit.",
            error_code="REVISION_CONFLICT",
        )
    if status not in (200, 201):
        die(_common.EXIT_API_ERROR,
            f"could not save the edit ({action}, {status}): {_common.api_message(payload)}")
    if revision is None:
        return None
    header = _http.last_headers.get("x-transcript-revision")
    if header and header.isdigit():
        return int(header)
    # A server without the header: read it back rather than guess.
    return _cards.read_editor(base, headers, job_id)[1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Change specific cards in one language.")
    parser.add_argument("--job-id", required=True, help="The dub's job id.")
    parser.add_argument("--language", required=True, help="Language key (a target, or the source for text).")
    parser.add_argument("--edits", required=True, help="JSON edits — see the script header.")
    parser.add_argument(
        "--revision", type=int,
        help="The revision inspect_process reported. Refuses the edit if the "
             "transcript changed since. Defaults to the revision read now.",
    )
    parser.add_argument("--dry-run", action="store_true", help="Show before/after, change nothing.")
    args = parser.parse_args()

    edits = parse_edits(args.edits)
    base = _common.base_url()
    headers = _common.headers()
    lang = args.language

    status_row = get_status(base, headers, args.job_id)
    source_lang = status_row.get("sourceLanguage")
    targets = status_row.get("targetLanguages") or []
    is_source = lang == source_lang
    if not is_source and lang not in targets:
        die(_common.EXIT_API_ERROR, f"{lang} is not a language of this dub.")
    if is_source and any(set(e) - {"card_id", "text", "start", "end"} for e in edits):
        die(_common.EXIT_API_ERROR,
            "only text and timing can be changed in the source language; emotion, "
            "rate, Keep Source, lip-sync, review status and volume belong to a "
            "dubbed language.")

    cards, current = _cards.read_editor(base, headers, args.job_id)
    if args.revision is not None and current is not None and args.revision != current:
        die(
            _common.EXIT_API_ERROR,
            f"the transcript changed since it was inspected (revision {args.revision} -> "
            f"{current}). Re-run inspect_process and redo the edit.",
            error_code="REVISION_CONFLICT",
            current_revision=current,
        )
    revision = args.revision if args.revision is not None else current

    # Validate everything against the current cards before sending anything.
    index = _cards.by_id(cards)
    changes, text_data, grouped, stale = [], [], {}, set()
    volume_calls = []
    duration = _cards.video_duration()
    for edit in edits:
        cid = edit["card_id"]
        card = index.get(cid)
        if card is None:
            die(_common.EXIT_API_ERROR, f"card {cid} is not in this dub.")
        blk = _cards.block(card, lang)
        if not blk:
            die(_common.EXIT_API_ERROR, f"card {cid} has no {lang} line.")
        update: dict = {}
        if "text" in edit:
            tr = blk.get("tr") if isinstance(blk.get("tr"), dict) else {}
            if tr.get("text") != edit["text"]:
                update["tr"] = with_text(tr, edit["text"])
                changes.append({"card_id": cid, "field": "text", "before": tr.get("text"), "after": edit["text"]})
        if "start" in edit or "end" in edit:
            v = blk.get("v") if isinstance(blk.get("v"), dict) else {}
            st = edit.get("start", v.get("st"))
            et = edit.get("end", v.get("et"))
            if st is None or et is None or st >= et:
                die(_common.EXIT_API_ERROR, f"card {cid}: start must be before end ({st} / {et}).")
            if duration and et > duration + 1e-6:
                die(_common.EXIT_API_ERROR, f"card {cid}: end {et}s is past the end of the video ({duration}s).")
            prev, nxt = _cards.neighbours(cards, cid, lang)
            prev_end = (_cards.block(prev, lang).get("v") or {}).get("et") if prev else None
            next_start = (_cards.block(nxt, lang).get("v") or {}).get("st") if nxt else None
            if prev_end is not None and st < prev_end - 1e-6:
                die(_common.EXIT_API_ERROR, f"card {cid}: start {st}s overlaps the previous line (ends {prev_end}s).")
            if next_start is not None and et > next_start + 1e-6:
                die(_common.EXIT_API_ERROR, f"card {cid}: end {et}s overlaps the next line (starts {next_start}s).")
            if (st, et) != (v.get("st"), v.get("et")):
                # `v` goes WHOLE too — the one-level merge would drop the rest.
                update["v"] = {**v, "st": st, "et": et}
                for field, old, new in (("start", v.get("st"), st), ("end", v.get("et"), et)):
                    if old != new:
                        changes.append({"card_id": cid, "field": field, "before": old, "after": new})
        if update:
            text_data.append({"id": card.get("id"), lang: update})
        if "volume" in edit:
            audio = blk.get("a") if isinstance(blk.get("a"), dict) else {}
            if not audio.get("url"):
                die(_common.EXIT_API_ERROR, f"card {cid} has no audio to set the volume of.")
            if audio.get("volume") != edit["volume"]:
                volume_calls.append({"transcriptId": cid, "language": lang, "volume": edit["volume"]})
                changes.append({"card_id": cid, "field": "volume", "before": audio.get("volume"), "after": edit["volume"]})
        for field, (action, key, read) in TOGGLES.items():
            if field not in edit:
                continue
            before = read(blk)
            if field == "rate" and blk.get("keepSourceAudio"):
                die(_common.EXIT_API_ERROR, f"card {cid} plays the original audio (Keep Source); its rate cannot change.")
            if before == edit[field]:
                continue
            grouped.setdefault((action, key, edit[field]), []).append(cid)
            changes.append({"card_id": cid, "field": field, "before": before, "after": edit[field]})
        if any(c["card_id"] == cid and c["field"] in STALE_FIELDS for c in changes):
            if not is_source and _cards.audio_of(card, lang):
                stale.add(cid)

    affected = [t for t in targets if is_source and any(c["field"] == "text" for c in changes)]
    result = {
        "language": lang,
        "revision_before": revision,
        "changes": changes,
        "audio_stale": sorted(stale),
        "affected_languages": affected,
    }
    if not changes:
        print(json.dumps({"status": "unchanged", **result, "revision_after": revision,
                          "next_action": "list_issues"}))
        return _common.EXIT_OK
    if args.dry_run:
        print(json.dumps({"status": "dry_run", **result, "revision_after": None,
                          "next_action": "patch_cards"}))
        return _common.EXIT_OK
    if revision is None:
        sys.stderr.write("[patch] server did not report a revision; this edit is not "
                         "protected against a concurrent change\n")

    if text_data:
        revision = send(base, headers, args.job_id, "update", text_data, revision)
    for (action, key, value), ids in grouped.items():
        data = {"updateType": "selected", "language": lang, "transcriptIds": ids, key: value}
        revision = send(base, headers, args.job_id, action, data, revision)
    for data in volume_calls:
        revision = send(base, headers, args.job_id, "saveAudio", data, revision)

    # Report what was SAVED, not what was asked for: the server may adjust a
    # value (a rate whose implied video speed is out of range is replaced by
    # the best in-range rate, exactly as in the editor).
    after_cards, _ = _cards.read_editor(base, headers, args.job_id)
    after_index = _cards.by_id(after_cards)
    readers = {
        "text": lambda b: (b.get("tr") or {}).get("text") if isinstance(b.get("tr"), dict) else None,
        "start": lambda b: (b.get("v") or {}).get("st"),
        "end": lambda b: (b.get("v") or {}).get("et"),
        "volume": lambda b: (b.get("a") or {}).get("volume") if isinstance(b.get("a"), dict) else None,
        **{f: spec[2] for f, spec in TOGGLES.items()},
    }
    for change in changes:
        blk = _cards.block(after_index.get(change["card_id"], {}), lang)
        applied = readers[change["field"]](blk) if change["field"] in readers else change["after"]
        if applied != change["after"]:
            change["requested"] = change["after"]
            change["after"] = applied
            change["adjusted_by_server"] = True
    result["changes"] = changes

    # What happened to the audio of the edited lines, as saved: the server
    # REMOVES a dubbed line's audio when its text changes (the line then
    # reports "No Audio"). An emotion change keeps the old clip — that one is
    # stale. A server that still keeps audio after a text edit is handled the
    # same way as emotion, so the old clip can never be exported unnoticed.
    cleared = sorted(
        cid for cid in stale
        if not _cards.audio_of(after_index.get(cid, {}), lang)
    )
    stale = {cid for cid in stale if cid not in cleared}
    result["audio_cleared"] = cleared
    result["audio_stale"] = sorted(stale)

    saved = _common.load_manifest(args.job_id)
    prior = set(((saved.get("audio_stale") or {}).get(lang)) or []) - set(cleared)
    _common.update_manifest(args.job_id, audio_stale={lang: sorted(prior | stale)}, revision=revision)

    sys.stderr.write(f"[patch] {len(changes)} change(s) saved in {lang}\n")
    print(json.dumps({
        "status": "patched", **result, "revision_after": revision,
        "next_action": "regenerate_cards" if stale or cleared else ("retranslate" if affected else "list_issues"),
    }))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
