#!/usr/bin/env python3
"""Adaptively resize an image to one or more target sizes (Vitra Adaptive Image).

Not a crop — the model re-composes the artwork for each target size.

Mirrors the webapp's four-step Adapts flow exactly:

  1. POST .../adapt/upload/presign   -> { designAssetId, uploadUrl, objectKey,
                                          objectUrl, headers }
  2. PUT  <uploadUrl>                 raw bytes, straight to S3
  3. POST .../adapt/assets            persist the asset row
  4. POST .../adapt/{id}/adapt        queue one variant per target size
     poll GET .../adapt/{id}/variants until each variant settles

Prints JSON:
  { "status": "completed",
    "outputs": [ { "label": "...", "dimension": "1080x1920", "image_url": "..." } ] }

Required env: VITRA_UNIVERSE_API_KEY (the key carries its organization).
Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
import mimetypes
import os
import re
import tempfile
import time
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _http  # noqa: E402

# Mounted at `adapt` (renamed from `design-agent` on 2026-08-26, after Adapts
# v1 was removed and freed the prefix). `design-agent` now 404s.
ADAPT = "/v1/galaxy/translate-photo/adapt"
PRESIGN_PATH = ADAPT + "/upload/presign"
ASSETS_PATH = ADAPT + "/assets"
VARIANTS_PATH = ADAPT + "/{asset_id}/adapt"
POLL_PATH = ADAPT + "/{asset_id}/variants"

MAX_SOURCE_BYTES = 50 * 1024 * 1024
DEFAULT_POLL_INTERVAL = 8
DEFAULT_MAX_WAIT = 900

# Variant lifecycle: PLAN_PENDING → GENERATING → REVIEW_PENDING/APPROVED/FAILED.
DONE = {"approved", "review_pending", "needs_review", "completed", "done"}
FAILED = {"failed", "rejected", "error", "cancelled"}
DIMENSION_RE = re.compile(r"^(\d+)x(\d+)$")

# Flash renders inline and lands APPROVED; PRO stops at PLAN_PENDING for human
# plan approval, which an unattended skill run cannot satisfy.
DEFAULT_TIER = "FLASH"

die = _common.die



# Magic bytes for the formats these APIs accept. Checked locally so an obvious
# non-image fails in milliseconds with a clear message, instead of after an
# upload and a queued render that costs credits.
_IMAGE_SIGNATURES = (
    (b"\x89PNG\r\n\x1a\n", "PNG"),
    (b"\xff\xd8\xff", "JPEG"),
    (b"GIF87a", "GIF"),
    (b"GIF89a", "GIF"),
    (b"BM", "BMP"),
)


def looks_like_image(path: Path) -> bool:
    """True when the file's leading bytes match a supported image format."""
    try:
        head = path.open("rb").read(16)
    except OSError:
        return False
    if any(head.startswith(sig) for sig, _ in _IMAGE_SIGNATURES):
        return True
    # WEBP: "RIFF" .... "WEBP";  TIFF: II*\0 / MM\0*
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return True
    return head[:4] in (b"II*\x00", b"MM\x00*")


def resolve_source(file_arg: str | None, url_arg: str | None) -> tuple[Path, bool]:
    if file_arg:
        p = Path(file_arg).expanduser()
        if not p.is_file():
            die(_common.EXIT_DOWNLOAD, f"--file not found: {p}")
        if p.stat().st_size > MAX_SOURCE_BYTES:
            die(_common.EXIT_DOWNLOAD, "image exceeds the 50MB limit")
        if not looks_like_image(p):
            die(
                _common.EXIT_DOWNLOAD,
                f"that file is not an image we can read: {p.name}\n"
                "Supported: PNG, JPEG, GIF, BMP, WEBP, TIFF.",
            )
        return p, False

    parsed = urlparse(url_arg or "")
    if parsed.scheme not in ("http", "https"):
        die(_common.EXIT_DOWNLOAD, "--url must be an http(s) URL")
    name = Path(parsed.path).name or "image.png"
    tmp = Path(tempfile.gettempdir()) / f"vitra-adapt-{os.getpid()}-{name}"
    try:
        n = _http.download_to_file(url_arg, tmp, MAX_SOURCE_BYTES)
    except _http.NetworkError as e:
        die(_common.EXIT_DOWNLOAD, f"could not download --url: {e}")
    except ValueError as e:
        die(_common.EXIT_DOWNLOAD, str(e))
    sys.stderr.write(f"[source] downloaded {n} bytes\n")
    # A URL can serve an HTML error page with a 200 — check the bytes, not the
    # status, before spending an upload and a render on it.
    if not looks_like_image(tmp):
        try:
            tmp.unlink()
        except OSError:
            pass
        die(
            _common.EXIT_DOWNLOAD,
            "that URL did not return an image (it may be a web page or an "
            "error page). Check the link points directly at an image file.",
        )
    return tmp, True


def parse_size(raw: str) -> tuple[int, int, str]:
    """`1080x1920` or `1080x1920=Instagram Story` -> (width, height, label)."""
    dimension, _, label = raw.partition("=")
    m = DIMENSION_RE.match(dimension.strip())
    if not m:
        die(_common.EXIT_API_ERROR, f"--size must be WIDTHxHEIGHT (got '{raw}')")
    w, h = int(m.group(1)), int(m.group(2))
    return w, h, (label.strip() or f"{w}x{h}")


def unwrap(payload: object) -> dict:
    body = payload if isinstance(payload, dict) else {}
    if "status" in body or "designAssetId" in body or "uploadUrl" in body:
        return body
    inner = body.get("data")
    return inner if isinstance(inner, dict) else body


def call(base: str, headers: dict, path: str, body: dict, label: str) -> dict:
    try:
        status, payload = _http.post_json(base + path, headers, body)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"network error on {label}: {e}")
    if status in (401, 403):
        die(_common.EXIT_AUTH_REJECTED, _common.auth_error(status))
    if status not in (200, 201, 202):
        die(
            _common.EXIT_API_ERROR,
            f"{label} failed ({status}): {_common.api_message(payload)}",
        )
    return unwrap(payload)


def upload(base: str, headers: dict, path: Path) -> tuple[str, dict]:
    """Steps 1-2: presign, then PUT the bytes straight to S3."""
    content_type = mimetypes.guess_type(path.name)[0] or "image/png"
    pre = call(
        base,
        headers,
        PRESIGN_PATH,
        {"fileName": path.name, "contentType": content_type, "name": path.name},
        "presign",
    )
    upload_url = pre.get("uploadUrl")
    asset_id = pre.get("designAssetId")
    if not upload_url or not asset_id:
        die(_common.EXIT_API_ERROR, f"bad presign response: {_common.api_message(pre)}")

    # Send back EXACTLY the headers the presign signed — no auth header.
    put_headers = pre.get("headers") or {"Content-Type": content_type}
    sys.stderr.write("[upload] putting bytes to S3…\n")
    try:
        code = _http.put_file(upload_url, put_headers, path)
    except _http.NetworkError as e:
        die(_common.EXIT_API_ERROR, f"S3 upload failed: {e}")
    if code not in (200, 201, 204):
        die(_common.EXIT_API_ERROR, f"S3 upload rejected ({code}).")
    return asset_id, pre


def collect(rows: list) -> list[dict]:
    out = []
    for v in rows:
        if not isinstance(v, dict):
            continue
        cfg = v.get("targetConfig") or {}
        w, h = cfg.get("width"), cfg.get("height")
        version = v.get("activeVersion") or v.get("version") or {}
        url = (
            v.get("generatedImageUrl")
            or v.get("previewImageUrl")
            or v.get("imageUrl")
            or v.get("outputUrl")
            or (version.get("imageUrl") if isinstance(version, dict) else None)
        )
        out.append(
            {
                "label": v.get("variantCategory") or cfg.get("label") or "",
                "dimension": f"{w}x{h}" if w and h else None,
                "status": str(v.get("status") or "").lower(),
                "image_url": url,
            }
        )
    return out


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Adaptively resize an image to one or more target sizes."
    )
    src = parser.add_mutually_exclusive_group(required=True)
    src.add_argument("--file", help="Local image path (max 50MB).")
    src.add_argument("--url", help="Public http(s) image URL (downloaded, then uploaded).")
    parser.add_argument(
        "--size",
        action="append",
        required=True,
        metavar="WxH[=Label]",
        help="Target size, e.g. 1080x1920 or 1080x1920='Instagram Story'. Repeatable.",
    )
    parser.add_argument("--name", help="Display name for the asset.")
    parser.add_argument(
        "--tier",
        default=DEFAULT_TIER,
        choices=["FLASH", "PRO"],
        help="FLASH (default) renders inline. PRO stops for human plan approval.",
    )
    parser.add_argument("--poll-interval", type=int, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--max-wait", type=int, default=DEFAULT_MAX_WAIT)
    args = parser.parse_args()

    sizes = [parse_size(s) for s in args.size]
    base = _common.base_url()
    headers = _common.headers()

    path, is_temp = resolve_source(args.file, args.url)
    try:
        asset_id, pre = upload(base, headers, path)

        # Step 3 — persist the asset row.
        call(
            base,
            headers,
            ASSETS_PATH,
            {
                "designAssetId": asset_id,
                "name": args.name or path.name,
                "tier": args.tier,
                "objectKey": pre.get("objectKey"),
                "objectUrl": pre.get("objectUrl"),
            },
            "create asset",
        )

        # Step 4 — queue one variant per requested size.
        call(
            base,
            headers,
            VARIANTS_PATH.format(asset_id=asset_id),
            {
                "variants": [
                    {
                        "variantCategory": label,
                        "targetConfig": {
                            "width": w,
                            "height": h,
                            "label": label,
                            "type": "custom",
                        },
                    }
                    for (w, h, label) in sizes
                ]
            },
            "create variants",
        )
        sys.stderr.write(f"[resize] asset={asset_id} sizes={len(sizes)}\n")

        deadline = time.monotonic() + args.max_wait
        last = None
        while True:
            try:
                code, payload = _http.get_json(
                    base + POLL_PATH.format(asset_id=asset_id), headers=headers
                )
            except _http.NetworkError as e:
                die(_common.EXIT_API_ERROR, f"network error polling variants: {e}")
            if code != 200:
                die(
                    _common.EXIT_API_ERROR,
                    f"variant poll failed ({code}): {_common.api_message(payload)}",
                )

            body = payload if isinstance(payload, dict) else {}
            rows = body.get("data") if isinstance(body.get("data"), list) else body
            if isinstance(rows, dict):
                rows = rows.get("variants") or rows.get("items") or []
            variants = collect(rows if isinstance(rows, list) else [])
            states = [v["status"] for v in variants]

            summary = f"{sum(s in DONE for s in states)}/{len(sizes)} done"
            if summary != last:
                sys.stderr.write(f"[poll] {summary}\n")
                last = summary

            if len(variants) >= len(sizes) and all(
                s in DONE or s in FAILED for s in states
            ):
                ready = [v for v in variants if v["status"] in DONE and v["image_url"]]
                if not ready:
                    die(_common.EXIT_API_ERROR, "every requested size failed to render.")
                break
            if time.monotonic() >= deadline:
                die(
                    _common.EXIT_TIMEOUT,
                    f"timed out after {args.max_wait}s waiting for the resizes.",
                )
            time.sleep(args.poll_interval)
    finally:
        if is_temp:
            try:
                path.unlink()
            except OSError:
                pass

    print(
        json.dumps(
            {
                "status": "completed",
                "outputs": [
                    {
                        "label": v["label"],
                        "dimension": v["dimension"],
                        "image_url": v["image_url"],
                    }
                    for v in ready
                ],
            }
        )
    )
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
