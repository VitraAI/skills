"""Image-translation jobs shared by this skill's follow-up scripts.

A job is one analysed image; each language (and each edit) is a translation
version of it. People pick by language, never by version id.
"""

from __future__ import annotations

import _api
import _common

IT = "/v1/galaxy/translate-photo/image-translator"
DONE = {"completed", "done", "success"}
die = _common.die


def versions(job_id: str) -> list[dict]:
    """Every version of the job, newest first (the route answers {versions: [...]})."""
    got = _api.call("GET", f"{IT}/{job_id}/translations", what="read the image's translations",
                    not_found="that image translation was not found in this organization.")
    rows = got.get("versions") if isinstance(got, dict) and isinstance(got.get("versions"), list) else _api.rows(got)
    return [r for r in rows if isinstance(r, dict)]


def full(job_id: str, version_id: str) -> dict:
    """One version with its text regions (the list leaves them out)."""
    return _api.data(_api.call("GET", f"{IT}/{job_id}/translations/{version_id}", what="read the image"))


def latest(job_id: str, language: str | None) -> dict:
    """The newest finished version, for `language` if given."""
    done = [v for v in versions(job_id) if str(v.get("status") or "").lower() in DONE]
    if language:
        wanted = language.strip().lower()
        done = [v for v in done if wanted in (str(v.get("targetLanguage") or "").lower(),
                                              str(v.get("targetLanguageName") or "").lower())]
    if not done:
        have = sorted({str(v.get("targetLanguage")) for v in versions(job_id) if v.get("targetLanguage")})
        die(_common.EXIT_API_ERROR, f"this image has no finished {language or ''} translation.".replace("  ", " "),
            error_code="CHOICE_NEEDED", choices=have, ask="Which language's image?")
    newest = done[0]
    return {**newest, **full(job_id, str(newest["id"]))}


def regions(version: dict) -> list[tuple[str, dict]]:
    """The version's text regions in reading order: (region id, {source, translated, status})."""
    data = version.get("translationData") or {}
    return [(rid, r) for rid, r in data.items() if isinstance(r, dict) and (r.get("source") or r.get("translated"))]


def lines(version: dict) -> list[dict]:
    """What people see: numbered lines, no ids."""
    status = {"v": "verified", "a": "approved", "u": None}
    out = []
    for n, (_, r) in enumerate(regions(version), 1):
        row = {"line": n, "source": r.get("source"), "translation": r.get("translated")}
        if r.get("kept"):
            row["kept_original"] = True
        if status.get(r.get("status")):
            row["status"] = status[r.get("status")]
        out.append(row)
    return out


def region_ids(version: dict, numbers: str) -> list[str]:
    ids = [rid for rid, _ in regions(version)]
    if numbers.strip().lower() == "all":
        return ids
    try:
        wanted = [int(x) for x in numbers.split(",") if x.strip()]
    except ValueError:
        die(_common.EXIT_API_ERROR, 'lines are numbers like "1,3", or "all".')
    bad = [n for n in wanted if not 1 <= n <= len(ids)]
    if bad:
        die(_common.EXIT_API_ERROR, f"the image has lines 1 to {len(ids)}; {bad} don't exist.")
    return [ids[n - 1] for n in wanted]
