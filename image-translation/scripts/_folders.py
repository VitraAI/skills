"""Work folders: the webapp's folders that group jobs across products.

Single source: `sync-lib.sh` copies this file into the skills that file jobs
into folders. Edit it here only, then run the sync.

Image translations, dubs and documents each have a "move to folder" route
taking a folder id (or null for Unassigned). People name folders; the id is
looked up here and never shown.

Stdlib only.
"""

from __future__ import annotations

import _api
import _common

FOLDERS = "/v1/folder"
UNASSIGNED = {"none", "unassigned", "no folder"}
die = _common.die


def folder_id(name: str) -> str | None:
    """The folder called `name`; None for "Unassigned"; asks otherwise."""
    if name.strip().lower() in UNASSIGNED:
        return None
    folders = _api.rows(_api.call("GET", FOLDERS, what="list folders"))
    exact = [f for f in folders if str(f.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return str(exact[0]["id"])
    die(_common.EXIT_API_ERROR, f'no single folder is called "{name}".', error_code="CHOICE_NEEDED",
        choices=sorted({str(f.get("name")) for f in (exact or folders)})[:30] + ["Unassigned"],
        ask="Which folder? (Unassigned takes it out of every folder.)")
    return None  # unreachable


def move(path: str, name: str, what: str = "move it to the folder") -> dict:
    """PATCH a product's `…/{id}/folder` route."""
    _api.call("PATCH", path, {"folderId": folder_id(name)}, what=what)
    return {"status": "moved", "folder": "Unassigned" if name.strip().lower() in UNASSIGNED else name}
