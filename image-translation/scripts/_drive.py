"""Save a finished result into the organization's Drive (Asset Management).

Single source: `sync-lib.sh` copies this file into the skills that save to the
Drive. Edit it here only, then run the sync.

Every product's "Save to Drive" route takes the same two optional fields: a
folder and a file name. Without a folder, the product files it in its own
default folder. People name folders; the id is looked up here and never shown.

Stdlib only.
"""

from __future__ import annotations

from urllib.parse import urlencode

import _api
import _common

ASSETS = "/v1/assets-management"
die = _common.die


def folder_id(name: str) -> str:
    """The Drive folder called `name`; asks when there are several or none."""
    got = _api.rows(_api.call("GET", f"{ASSETS}?{urlencode({'keyword': name, 'searchScope': 'global', 'limit': 50})}",
                              what="search the Drive"))
    folders = [r for r in got if str(r.get("type") or "").lower() == "folder"]
    exact = [f for f in folders if str(f.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return str(exact[0]["id"])
    choices = sorted({str(f.get("name")) for f in (exact or folders)})
    die(_common.EXIT_API_ERROR, f'no single Drive folder is called "{name}".', error_code="CHOICE_NEEDED",
        choices=choices[:20], ask="Which Drive folder? Or leave it out to use the default folder.")
    return ""  # unreachable


def file_id(name: str) -> tuple[str, str]:
    """The Drive file called `name` (not a folder): (id, name); asks when unclear."""
    got = _api.rows(_api.call("GET", f"{ASSETS}?{urlencode({'keyword': name, 'searchScope': 'global', 'limit': 50})}",
                              what="search the Drive"))
    files = [r for r in got if str(r.get("type") or "").lower() != "folder"]
    exact = [f for f in files if str(f.get("name") or "").strip().lower() == name.strip().lower()]
    if len(exact) == 1:
        return str(exact[0]["id"]), str(exact[0].get("name"))
    die(_common.EXIT_API_ERROR, f'no single Drive file is called "{name}".', error_code="CHOICE_NEEDED",
        choices=sorted({str(f.get("name")) for f in (exact or files)})[:20], ask="Which file in the Drive?")
    return "", ""  # unreachable


def save(path: str, folder: str | None = None, name: str | None = None, what: str = "save it to the Drive") -> dict:
    """POST the product's save route; returns what to tell the user."""
    body = {**({"folderId": folder_id(folder)} if folder else {}), **({"name": name} if name else {})}
    got = _api.data(_api.call("POST", path, body, what=what, timeout=300))
    return {"status": "saved", "file": got.get("name") or name, "folder": folder or "the default folder"}
