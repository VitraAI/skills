#!/usr/bin/env python3
"""Download a finished export to disk, verifying it before declaring success.

Takes the export id from `export_dub.py`, refreshes its signed URL and streams
the bytes down. A signed URL expires; re-running this refreshes it for the SAME
export rather than rendering a second one.

  GET  .../process-log/{exportId}/editor-output -> stored media url
  POST .../process-log/presigned-export-url     -> a fresh signed url

Downloads to `<name>.partial`, checks it, then renames into place — so a
half-written file is never mistaken for a finished one. An interrupted download
RESUMES from the partial file (HTTP Range) on the next run; if the server will
not resume, it restarts — never by exporting again.

Checks before declaring success:
  * with ffprobe/ffmpeg on PATH: a video stream AND an audio stream, a real
    duration (and, with --job-id, within 2s of the dub's video), and that the
    opening, middle and ending all decode.
  * without them: the MP4 structure (`ftyp` + `moov` boxes) — reported as
    `"media_check": "basic"` so nobody mistakes it for a full check.

Prints JSON:
  { "status": "downloaded", "path": "...", "bytes": 12345678,
    "sha256": "...", "export_id": "...", "media_check": "full" | "basic",
    "media": { "duration_seconds", "video_codec", "audio_codec", ... } }

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import hashlib
import json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

PL = "/v1/galaxy/translate-video/process-log"
EDITOR_OUTPUT_PATH = PL + "/{child_id}/editor-output"
PRESIGN_PATH = PL + "/presigned-export-url"

# A finished render is never this small; anything under it is an error page or
# a truncated stream that happened to return 200.
MIN_PLAUSIBLE_BYTES = 10 * 1024

die = _common.die


def stored_media_url(base: str, headers: dict, export_id: str) -> str:
    try:
        status, payload = _http.get_json(
            base + EDITOR_OUTPUT_PATH.format(child_id=export_id), headers=headers
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error reading the export: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status, "read this export"))
    if status == 404:
        die(_common.EXIT_API_ERROR, "that export was not found in this organization.")
    if status != 200:
        die(
            _common.EXIT_API_ERROR,
            f"could not read the export ({status}): {_common.api_message(payload)}",
        )

    data = ((payload or {}).get("data") or {}).get("data") or {}
    bundle = data
    out = data.get("OUTPUT")
    if isinstance(out, list) and out and isinstance(out[0], dict):
        bundle = out[0]
    media = bundle.get("video") or bundle.get("audio")
    if not isinstance(media, str) or not media:
        die(
            _common.EXIT_API_ERROR,
            "that export has no media yet — it may still be rendering.",
        )
    return media


def refresh_signed_url(base: str, headers: dict, s3_url: str) -> str:
    """A signed URL expires; this mints a new one for the same object."""
    try:
        status, payload = _http.post_json(
            base + PRESIGN_PATH, headers, {"s3Url": s3_url}
        )
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error refreshing the download link: {e}")
    if status not in (200, 201):
        die(
            _common.EXIT_API_ERROR,
            f"could not refresh the download link ({status}): "
            f"{_common.api_message(payload)}",
        )
    data = (payload or {}).get("data") or {}
    url = data.get("url") if isinstance(data, dict) else None
    if not isinstance(url, str) or not url:
        die(_common.EXIT_API_ERROR, "no download link in the response.")
    return url


def fetch_resumable(url: str, partial: Path) -> int:
    """Stream into `partial`, continuing from its current size when possible."""
    import urllib.error
    import urllib.request

    have = partial.stat().st_size if partial.exists() else 0
    req = urllib.request.Request(url, headers={"Range": f"bytes={have}-"} if have else {})
    try:
        resp = urllib.request.urlopen(req, timeout=120)
    except urllib.error.HTTPError as e:
        if e.code == 416 and have:  # already complete
            return have
        raise ValueError(f"download returned HTTP {e.code}") from e
    except OSError as e:
        raise _http.NetworkError(_http.humanize(e)) from e
    with resp:
        resuming = have and resp.status == 206
        if have and not resuming:
            sys.stderr.write("[download] server cannot resume; starting over\n")
        mode = "ab" if resuming else "wb"
        written = have if resuming else 0
        try:
            with partial.open(mode) as fh:
                for chunk in iter(lambda: resp.read(1 << 20), b""):
                    fh.write(chunk)
                    written += len(chunk)
        except OSError as e:
            raise _http.NetworkError(_http.humanize(e)) from e
    return written


def _mp4_boxes(path: Path) -> set[str]:
    """Top-level MP4 box types, walking the size headers (no full read)."""
    import struct

    boxes, size_total = set(), path.stat().st_size
    with path.open("rb") as fh:
        pos = 0
        while pos + 8 <= size_total and len(boxes) < 64:
            fh.seek(pos)
            header = fh.read(16)
            size, kind = struct.unpack(">I4s", header[:8])
            if size == 1 and len(header) >= 16:
                size = struct.unpack(">Q", header[8:16])[0]
            elif size == 0:
                size = size_total - pos
            if size < 8:
                break
            boxes.add(kind.decode("latin-1"))
            pos += size
    return boxes


def check_media(path: Path, expected_seconds: float | None) -> tuple[str, dict]:
    """("full" | "basic", details). Dies when the file is not a playable video."""
    import shutil
    import subprocess

    if shutil.which("ffprobe") and shutil.which("ffmpeg"):
        probe = subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries",
             "format=duration:stream=codec_type,codec_name", "-of", "json", str(path)],
            capture_output=True, text=True,
        )
        try:
            info = json.loads(probe.stdout or "{}")
        except ValueError:
            info = {}
        streams = info.get("streams") or []
        video = next((s for s in streams if s.get("codec_type") == "video"), None)
        audio = next((s for s in streams if s.get("codec_type") == "audio"), None)
        try:
            duration = float((info.get("format") or {}).get("duration") or 0)
        except ValueError:
            duration = 0.0
        if not video:
            die(_common.EXIT_DOWNLOAD, "the file has no video stream.")
        if not audio:
            die(_common.EXIT_DOWNLOAD, "the file has no audio — the dub would be silent.")
        if duration <= 0:
            die(_common.EXIT_DOWNLOAD, "the file reports no duration; it is not a finished video.")
        if expected_seconds and abs(duration - expected_seconds) > 2.0:
            die(_common.EXIT_DOWNLOAD,
                f"the video is {duration:.1f}s but the source is {expected_seconds:.1f}s — truncated render?")
        for label, at in (("opening", 0.0), ("middle", duration / 2), ("ending", max(0.0, duration - 1.0))):
            run = subprocess.run(
                ["ffmpeg", "-v", "error", "-ss", f"{at:.2f}", "-i", str(path),
                 "-t", "1", "-f", "null", "-"],
                capture_output=True, text=True,
            )
            if run.returncode != 0 or run.stderr.strip():
                die(_common.EXIT_DOWNLOAD, f"the {label} of the video does not decode cleanly: "
                    + (run.stderr.strip().splitlines() or ["unknown error"])[0])
        return "full", {
            "duration_seconds": round(duration, 3),
            "video_codec": video.get("codec_name"),
            "audio_codec": audio.get("codec_name"),
            "decoded": ["opening", "middle", "ending"],
        }

    boxes = _mp4_boxes(path)
    if "ftyp" not in boxes or "moov" not in boxes:
        die(_common.EXIT_DOWNLOAD, "the file is not a complete MP4 (missing ftyp/moov).")
    return "basic", {"boxes": sorted(boxes),
                     "note": "install ffmpeg for stream, duration and decode checks"}


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Download a finished export, verifying it before declaring success."
    )
    parser.add_argument(
        "--export-id",
        required=True,
        help="The export_id returned by export_dub.py.",
    )
    parser.add_argument(
        "--out",
        required=True,
        help="Where to write the file, e.g. ./dub-hindi.mp4",
    )
    parser.add_argument(
        "--job-id",
        help="The dub's job id — to compare the video's length with the source.",
    )
    args = parser.parse_args()

    base = _common.base_url()
    headers = _common.headers()

    dest = Path(args.out).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    partial = dest.with_suffix(dest.suffix + ".partial")

    media = stored_media_url(base, headers, args.export_id)
    url = refresh_signed_url(base, headers, media)

    sys.stderr.write("[download] streaming…\n")
    try:
        # No size cap: an exported video legitimately runs to many GB.
        written = fetch_resumable(url, partial)
    except _http.NetworkError as e:
        die(
            _common.EXIT_DOWNLOAD,
            f"the download was interrupted ({e}). The partial file is kept at "
            f"{partial} — re-run this command to resume. Do NOT export "
            "again; the render already exists.",
        )
    except ValueError as e:
        die(_common.EXIT_DOWNLOAD, str(e))

    if written < MIN_PLAUSIBLE_BYTES:
        try:
            partial.unlink()
        except OSError:
            pass
        die(
            _common.EXIT_DOWNLOAD,
            f"the download returned only {written} bytes — too small to be a "
            "video. The signed link may have expired; re-run to refresh it.",
        )

    expected = None
    if args.job_id:
        import _cards

        _cards.read_editor(base, headers, args.job_id)
        expected = _cards.video_duration() or None
    check_level, media_info = check_media(partial, expected)

    checksum = sha256_of(partial)
    # Atomic on the same filesystem: the finished name never exists half-written.
    partial.replace(dest)

    print(
        json.dumps(
            {
                "status": "downloaded",
                "path": str(dest),
                "bytes": written,
                "sha256": checksum,
                "export_id": args.export_id,
                "media_check": check_level,
                "media": media_info,
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
