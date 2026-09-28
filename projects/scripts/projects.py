#!/usr/bin/env python3
"""The organization's projects: see, create, change, delete, and who is on them.

  list     [--search TEXT] [--status NAME]
  show     --project NAME
  create   --name N --type TYPE [fields]
  update   --project NAME [--rename N] [fields]
  delete   --project NAME --confirm
  members  --project NAME [--add PERSON…] [--watch PERSON…] [--remove PERSON…]

fields: --description, --source-language (create only), --target-language
        (repeat; replaces the list), --start/--due YYYY-MM-DD, --status NAME,
        --priority NAME, --tag (repeat; replaces the tags)

Routes: /v1/project, /v1/project-template, /v1/task-template/project/{id},
        /v1/project-member/{add,remove,:projectId}, organization member lookup

Prints JSON: { "status", "project" | "projects" | "members", … }. Projects,
statuses, priorities and people are named; ids never leave this script.

Needs a Vitra sign-in (login.py) or VITRA_UNIVERSE_API_KEY. Stdlib only.
"""

from __future__ import annotations

import sys

sys.dont_write_bytecode = True  # don't litter __pycache__/ in the skill folder

import argparse
import json
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, str(Path(__file__).parent))
import _common  # noqa: E402
import _work  # noqa: E402

TYPES = ["TRANSLATION", "LOCALIZATION", "TRANSCRIPTION", "SUBTITLING", "VOICEOVER", "REVIEW"]
die = _common.die


def present(p: dict, board: list[dict], prios: list[dict], full: bool = False) -> dict:
    total, done = int(p.get("taskCount") or 0), int(p.get("completedTaskCount") or 0)
    people = [m for m in p.get("members") or [] if isinstance(m, dict)]
    out = {
        "name": p.get("name"), "type": p.get("type"),
        "status": _work.name_of(board, p.get("status")), "priority": _work.name_of(prios, p.get("priority")),
        "from": p.get("sourceLanguage") or None, "to": p.get("targetLanguages") or None,
        "start": _work.day(p.get("startDate")), "due": _work.day(p.get("endDate")),
        "tasks": f"{done}/{total} done" if total else "no tasks",
        "people": [_work.person(m) for m in people if m.get("isAssignee")] or None,
    }
    if full:
        out |= {"description": p.get("description") or None, "tags": p.get("tags") or None,
                "watchers": [_work.person(m) for m in people if m.get("isWatcher") and not m.get("isAssignee")]
                or None}
    return {k: v for k, v in out.items() if v is not None}


def fields(args: argparse.Namespace, board: list[dict], prios: list[dict]) -> dict:
    body: dict = {}
    if args.description is not None:
        body["description"] = args.description
    if args.target_language:
        body["targetLanguages"] = [_work.language_key(x) for x in args.target_language]
    for flag, key in (("start", "startDate"), ("due", "endDate")):
        if getattr(args, flag):
            body[key] = _work.date(getattr(args, flag), "--" + flag)
    if args.status:
        body["status"] = _work.id_of(board, args.status, "project status")
    if args.priority:
        body["priority"] = _work.id_of(prios, args.priority, "priority")
    if args.tag:
        body["tags"] = args.tag
    return body


def members(project: dict, args: argparse.Namespace) -> dict:
    pid = str(project["id"])
    changed: list[str] = []
    wanted = [(w, False) for w in args.add or []] + [(w, True) for w in args.watch or []]
    if wanted:
        people = [(_work.org_member(project, who), watch) for who, watch in wanted]
        _work.call("POST", "/v1/project-member/add", {"fk_projectId": pid, "members": [
            {"orgMemberId": m["id"], "isAssignee": not watch, "isWatcher": watch} for m, watch in people]},
            what="add people to the project")
        changed += [f"added {m['name']}" + (" as a watcher" if watch else "") for m, watch in people]
    if args.remove:
        current = _work.rows(_work.call("GET", f"/v1/project-member/{quote(pid)}", what="read the project's people"))
        gone = []
        for who in args.remove:
            hit = [m for m in current if who.strip().lower() in
                   (str(_work.person(m) or "").lower(), str(((m.get("orgMember") or {}).get("user") or {})
                                                        .get("email") or "").lower())]
            if len(hit) != 1:
                _work.ask_choice("person on this project", who, [str(_work.person(m)) for m in current])
            gone.append(hit[0])
        _work.call("DELETE", "/v1/project-member/remove", {"fk_projectId": pid, "orgMemberIds": [
            str(m.get("fk_orgMemberId") or (m.get("orgMember") or {}).get("id")) for m in gone]},
            what="remove people from the project")
        changed += [f"removed {_work.person(m)}" for m in gone]
    now = _work.rows(_work.call("GET", f"/v1/project-member/{quote(pid)}", what="read the project's people"))
    return {"status": "updated" if changed else "ok", "project": project.get("name"), "changed": changed or None,
            "members": [{"name": _work.person(m), "role": "assignee" if m.get("isAssignee") else "watcher"}
                        for m in now]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage projects.")
    parser.add_argument("action", choices=["list", "show", "create", "update", "delete", "members"])
    parser.add_argument("--project", help="The project's name.")
    parser.add_argument("--search")
    parser.add_argument("--name", help="create: the new project's name.")
    parser.add_argument("--rename")
    parser.add_argument("--type", choices=TYPES, type=str.upper)
    parser.add_argument("--description")
    parser.add_argument("--source-language")
    parser.add_argument("--target-language", action="append")
    parser.add_argument("--start")
    parser.add_argument("--due")
    parser.add_argument("--status")
    parser.add_argument("--priority")
    parser.add_argument("--tag", action="append")
    parser.add_argument("--add", action="append", metavar="PERSON", help="members: add as an assignee.")
    parser.add_argument("--watch", action="append", metavar="PERSON", help="members: add as a watcher.")
    parser.add_argument("--remove", action="append", metavar="PERSON")
    parser.add_argument("--limit", type=int, default=25)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    org = _work.org_board()
    board, prios = _work.statuses(org), _work.priorities(org)

    if args.action == "list":
        q = {"limit": max(1, min(args.limit, 100)), **({"keyword": args.search} if args.search else {})}
        if args.status:
            q["status"] = _work.id_of(board, args.status, "project status")
        got = _work.call("GET", "/v1/project?" + urlencode(q), what="list projects")
        total = (got.get("pagination") or {}).get("total") if isinstance(got, dict) else None
        found = [present(p, board, prios) for p in _work.rows(got)]
        print(json.dumps({"status": "ok", "count": total if total is not None else len(found), "projects": found,
                          "statuses": _work.names(org)["statuses"]}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "create":
        if not (args.name and args.type):
            die(_common.EXIT_API_ERROR, "a project needs --name and --type.", error_code="CHOICE_NEEDED",
                choices=TYPES, ask="What kind of project is it?")
        body = {"name": args.name, "type": args.type, **fields(args, board, prios)}
        if args.source_language:
            body["sourceLanguage"] = _work.language_key(args.source_language)
        made = _work.call("POST", "/v1/project", body, what="create the project")
        made = made.get("data") if isinstance(made, dict) and isinstance(made.get("data"), dict) else made
        print(json.dumps({"status": "created", "project": present(made, board, prios)}, ensure_ascii=False))
        return _common.EXIT_OK

    if not args.project:
        die(_common.EXIT_API_ERROR, "--project is required.")
    project = _work.find_project(args.project)
    pid = quote(str(project["id"]))

    if args.action == "show":
        full = _work.call("GET", f"/v1/project/{pid}", what="read the project")
        full = full.get("data") if isinstance(full, dict) and isinstance(full.get("data"), dict) else full
        print(json.dumps({"status": "ok", "project": present(full, board, prios, full=True),
                          "task_board": _work.names(_work.task_board(project))}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "update":
        body = fields(args, board, prios)
        if args.rename:
            body["name"] = args.rename
        if args.type:
            body["type"] = args.type
        if not body:
            die(_common.EXIT_API_ERROR, "nothing to change: pass the fields to update.")
        _work.call("PUT", f"/v1/project/{pid}", body, what="update the project")
        fresh = _work.call("GET", f"/v1/project/{pid}", what="read the project")
        fresh = fresh.get("data") if isinstance(fresh, dict) and isinstance(fresh.get("data"), dict) else fresh
        print(json.dumps({"status": "updated", "project": present(fresh, board, prios)}, ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "members":
        print(json.dumps(members(project, args), ensure_ascii=False))
        return _common.EXIT_OK

    if not args.confirm:  # delete
        die(_common.EXIT_API_ERROR, "deleting a project can't be undone.", error_code="CONFIRM_NEEDED",
            ask=f'Delete the project "{project.get("name")}"? Then run the same command with --confirm.')
    _work.call("DELETE", f"/v1/project/{pid}", what="delete the project")
    print(json.dumps({"status": "deleted", "project": project.get("name")}, ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
