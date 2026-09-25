"""The organization's saved instant-clone voices, and how to reference one.

A saved clone must be sent as `voiceType: "instant-clone"` with its id.
Sent as a bare voiceId, the full-run pipeline happens to cope, but the
single-line speech route looks it up as a catalog ("standard") voice and
fails with 404 — so every script that assigns or uses a voice goes through
here.
"""

from __future__ import annotations

import _http

CLONED_VOICES_PATH = "/v1/galaxy/translate-video/voice/cloned"
INSTANT_CLONE = "instant-clone"


def list_cloned(base: str, headers: dict) -> list[dict]:
    """Ready saved clones as {voice_id, name, gender, preview_url,
    supported_languages}. Best-effort: [] on any failure."""
    try:
        status, payload = _http.get_json(
            f"{base}{CLONED_VOICES_PATH}?all=true&isActive=true", headers=headers
        )
    except _http.NetworkError:
        return []
    if status != 200:
        return []
    rows = payload if isinstance(payload, list) else (payload or {}).get("data", [])
    if isinstance(rows, dict):
        rows = rows.get("data", [])
    out = []
    for v in rows or []:
        if not isinstance(v, dict) or v.get("status") not in (None, "ready"):
            continue
        out.append({
            "voice_id": v.get("id") or v.get("providerVoiceId"),
            "name": v.get("name") or "",
            "gender": v.get("gender") or "",
            "preview_url": v.get("previewUrl"),
            "supported_languages": v.get("supportedLanguages") or [],
        })
    return out


def as_voice(voice_id: str, clones: list[dict], fallback_name: str = "") -> dict:
    """The voice fields for an id: a saved clone is typed instant-clone and
    named; anything else is passed as a catalog voice id."""
    clone = next((c for c in clones if c["voice_id"] == voice_id), None)
    if clone:
        return {"voiceId": voice_id, "voiceName": clone["name"] or fallback_name,
                "voiceType": INSTANT_CLONE}
    return {"voiceId": voice_id, "voiceName": fallback_name}
