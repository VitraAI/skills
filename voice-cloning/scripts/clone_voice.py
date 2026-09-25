#!/usr/bin/env python3
"""Clone a voice from 1–5 audio samples; it's ready to speak when this ends.

  POST /v1/galaxy/playground/voice-clone   multipart `samples` + name, provider

The voice then appears in list_voices.py (as cloned) and can speak any text
with text-to-speech, or voice a speaker in a dub.

Prints JSON: { "status": "ready" | "failed" | "processing", "voice": {"name",
               "provider", "voice_id", "preview_url"}, "next_action" }

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
import _http  # noqa: E402
import _state  # noqa: E402

CLONE = "/v1/galaxy/playground/voice-clone"
AUDIO = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac", ".webm"}
MAX_SAMPLES = 5
die = _common.die


def main() -> int:
    parser = argparse.ArgumentParser(description="Clone a voice from audio samples.")
    parser.add_argument("--sample", action="append", required=True, help="An audio sample (repeat, up to 5).")
    parser.add_argument("--name", required=True, help="What to call the voice.")
    parser.add_argument("--provider", default="elevenlabs", choices=["elevenlabs", "cartesia"])
    parser.add_argument("--language", help="Language key the voice speaks, e.g. english_united_states.")
    parser.add_argument("--gender", choices=["male", "female", "neutral"])
    parser.add_argument("--description", help="A short note, e.g. 'Priya, warm narration'.")
    parser.add_argument("--remove-background-noise", action="store_true")
    args = parser.parse_args()

    samples = [Path(s).expanduser() for s in args.sample]
    if len(samples) > MAX_SAMPLES:
        die(_common.EXIT_API_ERROR, f"at most {MAX_SAMPLES} samples.")
    for s in samples:
        if not s.is_file():
            die(_common.EXIT_DOWNLOAD, f"sample not found: {s}")
        if s.suffix.lower() not in AUDIO:
            die(_common.EXIT_API_ERROR, f"{s.name} is not an audio file ({', '.join(sorted(AUDIO))}).")

    key = _common.idempotency_key("clone", sorted(_common.sha256_file(s) for s in samples), args.name,
                                  args.provider)
    if (known := _state.recall("voice-cloning", key)) and known.get("voice"):
        sys.stderr.write("[clone] this voice was already cloned from these samples\n")
        print(json.dumps({"status": "ready", "voice": known["voice"], "next_action": None}))
        return _common.EXIT_OK

    fields = {"name": args.name, "provider": args.provider,
              **{k: v for k, v in {"language": args.language, "gender": args.gender,
                                   "description": args.description}.items() if v}}
    if args.remove_background_noise:
        fields["removeBackgroundNoise"] = "true"
    sys.stderr.write(f"[clone] cloning from {len(samples)} sample(s); this can take a minute\n")
    try:
        status, payload = _http.post_multipart_files(
            _common.base_url() + CLONE, _common.headers(), [("samples", s) for s in samples], fields,
            timeout=900)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error cloning the voice: {e}", retryable=True)
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "clone voices"))
    if status == 402:
        die(_common.EXIT_API_ERROR, f"not enough credits: {_common.api_message(payload)}",
            error_code="INSUFFICIENT_CREDITS")
    if status not in (200, 201) or not isinstance(payload, dict):
        die(_common.EXIT_API_ERROR, f"the voice was not cloned ({status}): {_common.api_message(payload)}")
    row = payload.get("data") if isinstance(payload.get("data"), dict) else payload
    voice = {"name": row.get("name"), "provider": row.get("provider"),
             "voice_id": row.get("providerVoiceId"), "preview_url": row.get("previewUrl")}
    state = str(row.get("status") or "").lower()
    if state == "ready":
        _state.remember("voice-cloning", key, {"voice": voice})
    print(json.dumps({"status": state or "processing", "voice": voice,
                      "next_action": None if state == "ready" else "list_cloned_voices"}, ensure_ascii=False))
    return _common.EXIT_OK if state != "failed" else _common.EXIT_API_ERROR


if __name__ == "__main__":
    sys.exit(main())
