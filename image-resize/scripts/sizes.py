#!/usr/bin/env python3
"""Work with the sizes of a resized image: check, approve, redo, fix, save, export.

Every command takes --asset (the `asset` resize_image.py returned) and, where
it acts on one size, --size (its label, e.g. "Story", or its WxH, "1080x1920").

  list                                          each size: status, image, pending plan
  approve   --size S                            PRO: approve the layout plan so the image is made
  redo      --size S [--note "keep the logo top left"]   new image (with a note: new plan first)
  review    --size S                            PRO check: numbered issues with suggested fixes
  fix       --size S --issues 1,3|all [--note]  apply those fixes (new version)
  versions  --size S / restore --size S --version N
  save      --size S [--folder NAME]            into the Drive
  export    [--size S …] [--format png|jpeg] [--out-dir DIR]   download the files
  rename    --name N / move --folder NAME|Unassigned
  assets    [--limit 10]                        past resized images (no --asset needed)

Routes under /v1/galaxy/translate-photo/adapt: {asset}/variants, variants/{v}/approve-plan,
regenerate-image, regenerate-plan, review, fix-issues, versions, versions/{id}/activate,
save-to-drive, variants/export, assets/{asset}/rename, assets/{asset}/folder, assets.

Prints JSON; sizes by label and dimension, issues by number; no ids.
Required env: VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import base64
import json
import re
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).parent))
import _api  # noqa: E402
import _common  # noqa: E402
import _drive  # noqa: E402
import _folders  # noqa: E402

ADAPT = "/v1/galaxy/translate-photo/adapt"
die = _common.die


def label(v: dict) -> tuple[str, str]:
    cfg = v.get("targetConfig") or {}
    dim = f"{cfg.get('width')}x{cfg.get('height')}" if cfg.get("width") else ""
    return str(cfg.get("label") or v.get("variantCategory") or dim), dim


def sizes(asset: str) -> list[dict]:
    got = _api.call("GET", f"{ADAPT}/{quote(asset)}/variants", what="read the sizes",
                    not_found="that resized image was not found in this organization.")
    return _api.rows(got) or (got.get("variants") if isinstance(got, dict) else []) or []


def pick(asset: str, wanted: str | None) -> dict:
    rows = sizes(asset)
    if not wanted:
        if len(rows) == 1:
            return rows[0]
        die(_common.EXIT_API_ERROR, "which size?", error_code="CHOICE_NEEDED",
            choices=[" ".join(x for x in label(v) if x) for v in rows], ask="Which size?")
    w = wanted.strip().lower().replace("×", "x")
    hits = [v for v in rows if w in {x.lower() for x in label(v) if x}]
    if len(hits) != 1:
        die(_common.EXIT_API_ERROR, f'no single size is "{wanted}".', error_code="CHOICE_NEEDED",
            choices=[" ".join(x for x in label(v) if x) for v in rows], ask="Which size?")
    return hits[0]


def issues(variant: dict) -> list[dict]:
    """The PRO check's open issues, in a fixed order: text first, then visual."""
    review = variant.get("reviewData") or {}
    text = [i for i in (review.get("textReview") or {}).get("mapped_text") or []
            if i.get("status") in ("typo", "missing")]
    visual = [i for i in (review.get("visualReview") or {}).get("mapped_visuals") or []
              if i.get("status") in ("error", "missing")]
    out = []
    for i in text:
        out.append({"id": i.get("original_id"), "kind": f"text {i.get('status')}",
                    "found": i.get("detected_text"), "fix": i.get("suggested_correction")})
    for i in visual:
        out.append({"id": i.get("original_id"), "kind": f"{i.get('element_type') or 'visual'} {i.get('status')}",
                    "found": i.get("factual_observation"), "fix": i.get("suggested_correction")})
    return out


def show(v: dict) -> dict:
    name, dim = label(v)
    out = {"size": name, "dimension": dim or None, "status": str(v.get("status") or "").lower() or None,
           "image_url": v.get("generatedImageUrl") or v.get("previewImageUrl")}
    if str(v.get("status") or "").upper() == "PLAN_PENDING":
        out["next"] = "approve the plan (sizes.py approve)"
    n = len(issues(v))
    if n:
        out["issues"] = n
    return {k: x for k, x in out.items() if x is not None}


def main() -> int:
    parser = argparse.ArgumentParser(description="Work with the sizes of a resized image.")
    parser.add_argument("action", choices=["list", "approve", "redo", "review", "fix", "versions", "restore",
                                           "save", "export", "rename", "move", "assets"])
    parser.add_argument("--asset", help="The `asset` resize_image.py returned.")
    parser.add_argument("--size", action="append", help='A size by label ("Story") or WxH ("1080x1920").')
    parser.add_argument("--note", help="What to change, in plain words.")
    parser.add_argument("--issues", help='Issue numbers from review, e.g. "1,3", or "all".')
    parser.add_argument("--version", type=int)
    parser.add_argument("--folder")
    parser.add_argument("--name")
    parser.add_argument("--format", choices=["png", "jpeg"], default="png")
    parser.add_argument("--out-dir", default="resized")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    one = (args.size or [None])[0]

    if args.action == "assets":
        got = _api.call("GET", f"{ADAPT}/assets", what="list resized images")
        print(json.dumps({"status": "ok", "assets": [
            {"name": a.get("name"), "status": str(a.get("status") or "").lower(), "tier": a.get("tier"),
             "created": str(a.get("createdAt") or "")[:10], "asset": a.get("id")}
            for a in _api.rows(got)[:max(1, args.limit)]]},
            ensure_ascii=False))
        return _common.EXIT_OK
    if not args.asset:
        die(_common.EXIT_API_ERROR, "--asset is required (from resize_image.py, or sizes.py assets).")
    asset = quote(args.asset)

    if args.action == "list":
        print(json.dumps({"status": "ok", "sizes": [show(v) for v in sizes(args.asset)]}, ensure_ascii=False))
    elif args.action == "rename":
        if not args.name:
            die(_common.EXIT_API_ERROR, "--name is required.")
        _api.call("POST", f"{ADAPT}/assets/{asset}/rename", {"name": args.name}, what="rename the image")
        print(json.dumps({"status": "renamed", "name": args.name}, ensure_ascii=False))
    elif args.action == "move":
        if not args.folder:
            die(_common.EXIT_API_ERROR, "--folder is required (a folder name, or Unassigned).")
        print(json.dumps(_folders.move(f"{ADAPT}/assets/{asset}/folder", args.folder), ensure_ascii=False))
    elif args.action == "export":
        chosen = [pick(args.asset, s) for s in args.size] if args.size else sizes(args.asset)
        got = _api.data(_api.call("POST", f"{ADAPT}/variants/export",
                                  {"variantIds": [str(v["id"]) for v in chosen], "format": args.format},
                                  what="export the sizes", timeout=600))
        out_dir = Path(args.out_dir).expanduser()
        out_dir.mkdir(parents=True, exist_ok=True)
        names = {str(v["id"]): label(v)[0] for v in chosen}
        files, failed = [], []
        for r in got.get("results") or []:
            fname = re.sub(r"[^A-Za-z0-9._ -]+", "_", str(r.get("filename") or f"{names.get(str(r.get('variantId')))}.{args.format}"))
            (out_dir / fname).write_bytes(base64.b64decode(r.get("base64") or b""))
            files.append({"size": names.get(str(r.get("variantId"))), "path": str(out_dir / fname)})
        for r in got.get("failed") or []:
            failed.append({"size": names.get(str(r.get("variantId"))), "why": r.get("error")})
        print(json.dumps({"status": "exported" if not failed else "partial", "files": files,
                          **({"failed": failed} if failed else {})}, ensure_ascii=False))
    else:
        v = pick(args.asset, one)
        vid = quote(str(v["id"]))
        base = f"{ADAPT}/variants/{vid}"
        if args.action == "approve":
            _api.call("POST", f"{base}/approve-plan", {}, what="approve the plan", timeout=600)
            print(json.dumps({"status": "approved", "size": label(v)[0],
                              "next_action": "sizes.py list (the image is being made)"}, ensure_ascii=False))
        elif args.action == "redo":
            if args.note:
                _api.call("POST", f"{base}/regenerate-plan", {"generalNote": args.note}, what="redo the plan",
                          timeout=600)
            else:
                _api.call("POST", f"{base}/regenerate-image", {}, what="redo the image", timeout=600)
            print(json.dumps({"status": "redoing", "size": label(v)[0],
                              "next_action": "sizes.py list"}, ensure_ascii=False))
        elif args.action == "review":
            _api.call("POST", f"{base}/review", {}, what="check the image", timeout=600)
            fresh = _api.data(_api.call("GET", base, what="read the check"))
            found = issues(fresh)
            print(json.dumps({"status": "reviewed", "size": label(v)[0], "passed": not found,
                              "issues": [{"issue": n, **{k: x for k, x in i.items() if k != "id"}}
                                         for n, i in enumerate(found, 1)]}, ensure_ascii=False))
        elif args.action == "fix":
            found = issues(_api.data(_api.call("GET", base, what="read the check")))
            if not found:
                die(_common.EXIT_API_ERROR, "this size has no open issues; run review first.")
            if not args.issues:
                die(_common.EXIT_API_ERROR, '--issues is required: numbers from review, or "all".')
            if args.issues.strip().lower() == "all":
                ids = [i["id"] for i in found]
            else:
                try:
                    ids = [found[int(n) - 1]["id"] for n in args.issues.split(",") if n.strip()]
                except (ValueError, IndexError):
                    die(_common.EXIT_API_ERROR, f"issues are numbered 1 to {len(found)}.")
            _api.call("POST", f"{base}/fix-issues", {"selectedIssueIds": ids,
                                                     **({"additionalPrompt": args.note} if args.note else {})},
                      what="fix the issues", timeout=600)
            print(json.dumps({"status": "fixing", "size": label(v)[0], "issues": len(ids),
                              "next_action": "sizes.py list"}, ensure_ascii=False))
        elif args.action in ("versions", "restore"):
            rows = _api.rows(_api.call("GET", f"{base}/versions", what="read the versions"))
            if args.action == "versions":
                print(json.dumps({"status": "ok", "size": label(v)[0], "versions": [
                    {"version": r.get("versionNumber"), "made_by": r.get("originLabel") or r.get("originTaskType"),
                     "current": r.get("id") == v.get("fk_activeVersionId") or None,
                     "image_url": r.get("generatedImageUrl")} for r in rows]}, ensure_ascii=False))
            else:
                hit = next((r for r in rows if r.get("versionNumber") == args.version), None)
                if not hit:
                    die(_common.EXIT_API_ERROR, f"there is no version {args.version}.", error_code="CHOICE_NEEDED",
                        choices=[str(r.get("versionNumber")) for r in rows], ask="Which version?")
                _api.call("POST", f"{base}/versions/{quote(str(hit['id']))}/activate", {}, what="restore the version")
                print(json.dumps({"status": "restored", "size": label(v)[0], "version": args.version}))
        else:  # save
            out = _drive.save(f"{base}/save-to-drive", args.folder, None, what="save the size to the Drive")
            print(json.dumps({**out, "size": label(v)[0]}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
