"""Reading a dub's cards (one per dialogue line) from the editor document.

Shared by every script that looks at or changes cards, so they all agree on
where the cards live and what a card's audio state is.
"""

from __future__ import annotations

import _common
import _http

PL = "/v1/galaxy/translate-video/process-log"
EDITOR_OUTPUT_PATH = PL + "/{job_id}/editor-output?includeRevision=true"

# The document root from the last read_editor call (video duration etc.).
last_root: dict = {}


def read_editor(base: str, headers: dict, job_id: str) -> tuple[list, int | None]:
    """(cards, revision). revision is None on a server without revisions."""
    try:
        status, payload = _http.get_json(
            base + EDITOR_OUTPUT_PATH.format(job_id=job_id), headers=headers
        )
    except _http.NetworkError as e:
        _common.die(_common.EXIT_API_ERROR, f"network error reading the transcript: {e}")
    if status in (401, 403):
        _common.die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read the transcript"))
    if status == 404:
        _common.die(_common.EXIT_API_ERROR, "that dub was not found in this organization.")
    if status != 200:
        _common.die(
            _common.EXIT_API_ERROR,
            f"could not read the transcript ({status}): {_common.api_message(payload)}",
        )
    body = payload if isinstance(payload, dict) else {}
    editor = body.get("data") if isinstance(body.get("data"), dict) else body
    revision = editor.get("revision")

    # Cards live at data.OUTPUT[0].transcripts — the aggregate worker's
    # `{ OUTPUT: [root] }` envelope. Reading data.transcripts finds nothing.
    doc = editor.get("data") if isinstance(editor.get("data"), dict) else editor
    out = doc.get("OUTPUT")
    if isinstance(out, list) and out and isinstance(out[0], dict):
        doc = out[0]
    last_root.clear()
    last_root.update(doc if isinstance(doc, dict) else {})
    cards = doc.get("transcripts")
    return (
        [c for c in cards if isinstance(c, dict)] if isinstance(cards, list) else [],
        revision if isinstance(revision, int) else None,
    )


def block(card: dict, lang: str) -> dict:
    b = card.get(lang)
    return b if isinstance(b, dict) else {}


def audio_of(card: dict, lang: str) -> dict:
    """{url, duration_seconds, rate} for a card's current audio, or {} if none.

    `a.d` is SECONDS (a 4s clip reads 4.47). `a.r` is the playback rate — the
    player applies it; it is not baked into the file at `a.url`.
    """
    a = block(card, lang).get("a")
    if not isinstance(a, dict) or not a.get("url"):
        return {}
    return {"url": a.get("url"), "duration_seconds": a.get("d"), "rate": a.get("r")}


def by_id(cards: list) -> dict[str, dict]:
    return {str(c.get("id")): c for c in cards}


MAX_AUDIO_BYTES = 50 * 1024 * 1024  # one card's clip is seconds long; cap anything odd


def audio_hash(url: str | None) -> str | None:
    """sha256 of a card's current audio file, or None if it cannot be fetched.

    Needed because a regenerated clip keeps the SAME url (`<segmentId>.wav`),
    so the url alone cannot say whether the audio actually changed. The file
    is fetched exactly as the editor's player fetches it.
    """
    import hashlib
    import urllib.request

    if not url or not str(url).startswith(("http://", "https://")):
        return None
    digest = hashlib.sha256()
    read = 0
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            for chunk in iter(lambda: resp.read(1 << 16), b""):
                read += len(chunk)
                if read > MAX_AUDIO_BYTES:
                    return None
                digest.update(chunk)
    except Exception:  # noqa: BLE001 — any failure just means "unverified"
        return None
    return digest.hexdigest()


def fingerprint(card: dict, lang: str) -> dict:
    """What identifies a card's current audio: content hash, plus length/rate."""
    audio = audio_of(card, lang)
    if not audio:
        return {}
    return {**audio, "sha256": audio_hash(audio.get("url"))}


def video_duration() -> float:
    """Length of the video in seconds from the last read, 0 if unknown."""
    if isinstance(last_root.get("duration"), (int, float)):
        return float(last_root["duration"])
    for key in ("video_translation", "transcription"):
        nested = last_root.get(key)
        if isinstance(nested, dict) and isinstance(nested.get("duration"), (int, float)):
            return float(nested["duration"])
    return 0.0


def neighbours(cards: list, card_id: str, lang: str) -> tuple[dict | None, dict | None]:
    """The spoken cards just before and after this one in `lang` (gaps skipped)."""
    spoken = [c for c in cards if block(c, lang) and not c.get("isGap")]
    ids = [str(c.get("id")) for c in spoken]
    if card_id not in ids:
        return None, None
    i = ids.index(card_id)
    return (spoken[i - 1] if i > 0 else None, spoken[i + 1] if i + 1 < len(spoken) else None)
