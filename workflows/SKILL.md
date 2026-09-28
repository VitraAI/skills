---
name: workflows
description: >-
  Runs the automated workflows an organization built in Vitra Cosmos — chains
  of steps such as translate, dub, check and publish — with the inputs each
  needs, follows the run step by step, and relays the user's decision when a
  step waits for approval. Use it whenever the user names a process their team
  already automated — "run our product-launch workflow for the new video",
  "start the weekly localization flow", "approve the review step", "where is
  my workflow run?". Not for one-off jobs a specific skill does directly.
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs a
  Vitra sign-in (scripts/login.py opens the browser) or VITRA_UNIVERSE_API_KEY
  (a uvk_ key), for one Vitra organization.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Workflows
  category: Automation
  tags: Automation, Workflows
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Workflows

Runs Cosmos workflows the organization designed in Vitra. Each script prints
**one line of JSON** and follows the run until it finishes or a step waits for
the user.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps
their key can't do.

## The flow

```
- [ ] 1. Workflow and inputs   (⏸ which one; any missing inputs)
- [ ] 2. Run                   (⏸ confirm: its steps may spend credits)
- [ ] 3. Approvals             (⏸ the user decides each waiting step)
```

### 1. Workflow and inputs ⏸

```bash
python3 scripts/list_flows.py
```

Pick the workflow by name; ask for every `required` input it lists.

### 2. Run ⏸

```bash
python3 scripts/run_flow.py --flow "<name>" --input <key>=<value> [--input <key>=a,b] [--name "<run name>"]
```

Follows the run and prints its numbered `steps`. Ends `completed`,
`waiting_for_you`, or `failed` (with `error`). A multi-value input takes
comma-separated values. Running the same command again reconnects to the run.
Later: `python3 scripts/run_status.py --run <run>`.

### 3. Approvals ⏸

When `status` is `waiting_for_you`, show the waiting step (`name`, `asks`)
and ask the user. Then, with their decision:

```bash
python3 scripts/decide.py --run <run> --approve <step> --confirm
python3 scripts/decide.py --run <run> --reject <step> --reason "…" --confirm
python3 scripts/decide.py --run <run> --cancel --confirm
```

Rejecting ends the run; so does cancelling. Never decide for the user.

## Rules

- **Only the user approves, rejects or cancels.**
- **Name steps by number and name, never by id.**
- **Ask before starting a run**: its steps may spend credits.

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
`INPUT_NEEDED`, `CONFIRMATION_NEEDED`: ask `error.ask`. `NAME_UNKNOWN`: use a
name `list_flows.py` printed.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | Not signed in | Ask to sign in; on yes run `scripts/login.py`, then `login.py --status` once they finish |
| 3 | Key rejected or not allowed | Their Vitra admin must allow Cosmos for their role |
| 4 | API error, a question, or the run failed | Ask the question, or explain the message |
| 5 | Still running | It continues on its own; check later with run_status.py |
