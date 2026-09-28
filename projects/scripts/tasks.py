#!/usr/bin/env python3
"""Tasks inside a project: see, add, move along, assign, delete.

  list    --project NAME [--status NAME] [--mine] [--due-today] [--search TEXT]
  create  --project NAME --title T [fields] [--assign PERSON…]
  update  --project NAME --task TITLE [--rename T] [fields] [--assign PERSON…] [--unassign PERSON…]
  delete  --project NAME --task TITLE --confirm

fields: --description, --status NAME, --priority NAME, --start/--due YYYY-MM-DD,
        --source-language, --target-language, --tag (repeat; replaces the tags)

A title shared by several tasks: pass --nth N (1 = the first as listed).
Statuses and priorities are the project's own (see `projects.py show`).

Routes: /v1/task, /v1/task-template/project/{id}, /v1/task-member/{add,remove}

Prints JSON: { "status", "task" | "tasks", … }. Tasks, statuses and people are
named; ids never leave this script.

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

die = _common.die


def present(t: dict, board: list[dict], prios: list[dict]) -> dict:
    people = [m for m in t.get("taskMembers") or [] if isinstance(m, dict) and m.get("isAssignee")]
    out = {
        "task": t.get("title"), "status": _work.name_of(board, t.get("status")),
        "priority": _work.name_of(prios, t.get("priority")), "due": _work.day(t.get("endDate")),
        "done": _work.done_group(board, t.get("status")) or None,
        "language": " → ".join(x for x in (t.get("sourceLanguage"), t.get("targetLanguage")) if x) or None,
        "assignees": [_work.person(m) or (m.get("team") or {}).get("name") for m in people] or None,
    }
    return {k: v for k, v in out.items() if v is not None}


def find_task(project: dict, title: str, nth: int | None) -> dict:
    got = _work.rows(_work.call("GET", "/v1/task?" + urlencode(
        {"projectId": project["id"], "keyword": title, "limit": 100}), what="list tasks"))
    exact = [t for t in got if str(t.get("title") or "").strip().lower() == title.strip().lower()]
    if nth and 1 <= nth <= len(exact):
        return exact[nth - 1]
    if len(exact) == 1:
        return exact[0]
    if len(exact) > 1:
        die(_common.EXIT_API_ERROR, f'{len(exact)} tasks are called "{title}".', error_code="CHOICE_NEEDED",
            choices=[f'{i}. due {_work.day(t.get("endDate")) or "—"}' for i, t in enumerate(exact, 1)],
            ask="Which one? Then pass --nth with its number.")
    _work.ask_choice("task", title, sorted({str(t.get("title")) for t in got}))
    return {}  # unreachable


def fields(args: argparse.Namespace, board: list[dict], prios: list[dict]) -> dict:
    body: dict = {}
    if args.description is not None:
        body["description"] = args.description
    if args.status:
        body["status"] = _work.id_of(board, args.status, "task status")
    if args.priority:
        body["priority"] = _work.id_of(prios, args.priority, "priority")
    for flag, key in (("start", "startDate"), ("due", "endDate")):
        if getattr(args, flag):
            body[key] = _work.date(getattr(args, flag), "--" + flag)
    for flag, key in (("source_language", "sourceLanguage"), ("target_language", "targetLanguage")):
        if getattr(args, flag):
            body[key] = _work.language_key(getattr(args, flag))
    if args.tag:
        body["tags"] = args.tag
    return body


def assign(project: dict, task_id: str, add: list[str], drop: list[str], current: list[dict]) -> list[str]:
    changed = []
    if add:
        people = [_work.org_member(project, who) for who in add]
        _work.call("POST", "/v1/task-member/add", {"fk_taskId": task_id, "members": [
            {"orgMemberId": p["id"], "isAssignee": True, "isWatcher": False} for p in people]},
            what="assign the task")
        changed += [f"assigned {p['name']}" for p in people]
    if drop:
        gone = []
        for who in drop:
            hit = [m for m in current if who.strip().lower() in (
                str(_work.person(m) or "").lower(),
                str(((m.get("orgMember") or {}).get("user") or {}).get("email") or "").lower())]
            if len(hit) != 1:
                _work.ask_choice("assignee", who, [str(_work.person(m)) for m in current])
            gone.append(hit[0])
        _work.call("DELETE", "/v1/task-member/remove", {"fk_taskId": task_id, "orgMemberIds": [
            str(m.get("fk_orgMemberId") or (m.get("orgMember") or {}).get("id")) for m in gone]},
            what="unassign the task")
        changed += [f"unassigned {_work.person(m)}" for m in gone]
    return changed


def main() -> int:
    parser = argparse.ArgumentParser(description="Manage a project's tasks.")
    parser.add_argument("action", choices=["list", "create", "update", "delete"])
    parser.add_argument("--project", required=True)
    parser.add_argument("--task", help="The task's title (update, delete).")
    parser.add_argument("--nth", type=int)
    parser.add_argument("--title", help="create: the new task's title.")
    parser.add_argument("--rename")
    parser.add_argument("--description")
    parser.add_argument("--status")
    parser.add_argument("--priority")
    parser.add_argument("--start")
    parser.add_argument("--due")
    parser.add_argument("--source-language")
    parser.add_argument("--target-language")
    parser.add_argument("--tag", action="append")
    parser.add_argument("--assign", action="append", metavar="PERSON")
    parser.add_argument("--unassign", action="append", metavar="PERSON")
    parser.add_argument("--mine", action="store_true", help="list: only tasks assigned to me.")
    parser.add_argument("--due-today", action="store_true", help="list: due today or overdue, not closed.")
    parser.add_argument("--search")
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--confirm", action="store_true")
    args = parser.parse_args()

    project = _work.find_project(args.project)
    tb = _work.task_board(project)
    board, prios = _work.statuses(tb), _work.priorities(tb)

    if args.action == "list":
        q: dict = {"projectId": project["id"], "limit": max(1, min(args.limit, 100))}
        if args.status:
            q["status"] = _work.id_of(board, args.status, "task status")
        if args.mine:
            q["assignee"] = "me"
        if args.due_today:
            q["dueBy"] = "today-and-overdue"
        if args.search:
            q["keyword"] = args.search
        got = _work.call("GET", "/v1/task?" + urlencode(q), what="list tasks")
        total = (got.get("pagination") or {}).get("total") if isinstance(got, dict) else None
        found = [present(t, board, prios) for t in _work.rows(got)]
        print(json.dumps({"status": "ok", "project": project.get("name"),
                          "count": total if total is not None else len(found), "tasks": found},
                         ensure_ascii=False))
        return _common.EXIT_OK

    if args.action == "create":
        if not args.title:
            die(_common.EXIT_API_ERROR, "--title is required.")
        body = {"title": args.title, "fk_projectId": str(project["id"]), **fields(args, board, prios)}
        made = _work.call("POST", "/v1/task", body, what="create the task")
        made = made.get("data") if isinstance(made, dict) and isinstance(made.get("data"), dict) else made
        changed = assign(project, str(made["id"]), args.assign or [], [], []) if args.assign else []
        made["taskMembers"] = []
        out = present(made, board, prios)
        if changed:
            out["assignees"] = [c.removeprefix("assigned ") for c in changed]
        print(json.dumps({"status": "created", "project": project.get("name"), "task": out}, ensure_ascii=False))
        return _common.EXIT_OK

    if not args.task:
        die(_common.EXIT_API_ERROR, "--task is required (the task's title).")
    task = find_task(project, args.task, args.nth)
    tid = str(task["id"])

    if args.action == "update":
        body = fields(args, board, prios)
        if args.rename:
            body["title"] = args.rename
        if not (body or args.assign or args.unassign):
            die(_common.EXIT_API_ERROR, "nothing to change: pass the fields to update.")
        if body:
            _work.call("PUT", f"/v1/task/{quote(tid)}", body, what="update the task")
        current = [m for m in task.get("taskMembers") or [] if isinstance(m, dict)]
        changed = assign(project, tid, args.assign or [], args.unassign or [], current)
        fresh = _work.call("GET", f"/v1/task/{quote(tid)}", what="read the task")
        fresh = fresh.get("data") if isinstance(fresh, dict) and isinstance(fresh.get("data"), dict) else fresh
        print(json.dumps({"status": "updated", "project": project.get("name"),
                          "task": present(fresh, board, prios), "changed": changed or None}, ensure_ascii=False))
        return _common.EXIT_OK

    if not args.confirm:  # delete
        die(_common.EXIT_API_ERROR, "deleting a task can't be undone.", error_code="CONFIRM_NEEDED",
            ask=f'Delete the task "{task.get("title")}"? Then run the same command with --confirm.')
    _work.call("DELETE", f"/v1/task/{quote(tid)}", what="delete the task")
    print(json.dumps({"status": "deleted", "project": project.get("name"), "task": task.get("title")},
                     ensure_ascii=False))
    return _common.EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
