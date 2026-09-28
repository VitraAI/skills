---
name: projects
description: >-
  Runs the organization's localization projects and tasks in Vitra Universe:
  lists projects with their status, due dates and progress; creates and
  updates projects (type, languages, dates, status, priority); adds or removes
  people; and lists, creates, moves, assigns and deletes tasks, all by name.
  Use it when the user asks about or changes their work in Vitra — "what's
  due today?", "create a project to translate the app into Hindi and Tamil",
  "move the glossary task to In Progress", "assign it to Priya", "add Sam to
  the Q4 launch project". Doing the translation itself is other skills' job.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API only.
  Needs VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization).
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Projects & Tasks
  category: Productivity
  tags: Projects, Tasks, Productivity
  source: vitra
  added: "2026-09-28"
  updated: "2026-09-28"
---

# Projects & Tasks

Two scripts, each `<script> <action>`, each printing **one line of JSON**;
`status`, `error.ask` (a question for the user) and `next_action` drive the
flow. Everything is named: projects, tasks, statuses, priorities and people.
There are no ids to show.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `partial`: continue without the steps in
`cannot`. `blocked`: stop and tell the user which steps their key can't do;
their Vitra admin can grant them. Key missing (exit 2): relay the setup lines.

## Projects

```bash
python3 scripts/projects.py list [--search launch] [--status "In Progress"]
python3 scripts/projects.py show --project "Q4 launch"        # details, people, the task board
python3 scripts/projects.py create --name "App – Hindi & Tamil" --type TRANSLATION \
  [--source-language English] [--target-language Hindi --target-language Tamil] \
  [--due 2026-10-31] [--status …] [--priority High] [--description "…"] [--tag app]
python3 scripts/projects.py update --project "Q4 launch" [--rename …] [--due …] [--status …] [--priority …]
python3 scripts/projects.py members --project "Q4 launch" [--add "Priya Rao"] [--watch sam@acme.com] [--remove "Sam"]
python3 scripts/projects.py delete --project "Q4 launch"      # asks; then add --confirm
```

- **Type** is one of TRANSLATION, LOCALIZATION, TRANSCRIPTION, SUBTITLING,
  VOICEOVER, REVIEW. Ask if it isn't clear.
- **Status and priority** are names from the organization's board (`list`
  prints the statuses). Leave them out to start where Vitra starts new work.
- `--target-language` and `--tag` replace the whole list: pass every value.
- People are found by name or email. `--add` makes them an assignee,
  `--watch` a watcher.

## Tasks

Tasks live in a project; every command names it.

```bash
python3 scripts/tasks.py list --project "Q4 launch" [--status "To Do"] [--mine] [--due-today] [--search glossary]
python3 scripts/tasks.py create --project "Q4 launch" --title "Review glossary" \
  [--due 2026-10-10] [--priority High] [--status …] [--assign "Priya Rao"] [--target-language Hindi]
python3 scripts/tasks.py update --project "Q4 launch" --task "Review glossary" \
  [--status "In Progress"] [--due …] [--rename …] [--assign …] [--unassign …]
python3 scripts/tasks.py delete --project "Q4 launch" --task "Review glossary"   # asks; then --confirm
```

- A project's task statuses are its own (`projects.py show` lists them as
  `task_board`). `done: true` marks a task in a finished status.
- `--due-today` is due today or overdue, and not closed. `--mine` is tasks
  assigned to the key's owner.
- Two tasks with the same title: the script asks which (`choices`); pass
  `--nth <number>`.

## Rules

- **Show names, never ids.**
- **Confirm before changing others' work:** say what will change, then run it.
  Deletes always ask first (`CONFIRM_NEEDED`); pass `--confirm` only after the
  user says yes.
- `CHOICE_NEEDED` / `NOT_FOUND`: ask the question with the `choices` given;
  never guess a project, task, person or status.
- Keep answers short: summarize a long list (counts per status, what's due)
  rather than pasting every row.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
Explain `message` plainly; `retryable: true` → run the same command again.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow projects/tasks for their role |
| 4 | API error, or a question (`error.ask`) | Ask the question, or explain the message |
