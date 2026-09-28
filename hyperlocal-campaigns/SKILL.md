---
name: hyperlocal-campaigns
description: >-
  Runs Vitra Hyperlocal campaigns through the Vitra Universe API: picks an
  audience of retailers or partners (by group, state, zone or area), estimates
  reach and credits, prepares a personalized creative for every contact, then
  — only on the user's explicit yes — sends it over WhatsApp or Facebook now
  or on a schedule, and reports delivery (sent, delivered, read). Use it
  whenever the user wants to message their contact network — "send the Diwali
  offer to all retailers in Maharashtra", "schedule a WhatsApp campaign for
  tomorrow 10am", "how did last week's broadcast do?", "pause the campaign". A
  campaign is not a board project (projects). Not for translating content
  (document-translation, image-translation).
compatibility: >-
  Python 3.10+, standard library only; outbound HTTPS to the Vitra API. Needs
  VITRA_UNIVERSE_API_KEY (a uvk_ key for one Vitra organization) whose
  organization has Hyperlocal and a connected WhatsApp or Facebook account.
metadata:
  skill-author: Vitra.ai
  version: "1.0"
  display-name: Hyperlocal Campaigns
  category: Marketing
  tags: WhatsApp, Campaigns
  source: vitra
  added: "2026-09-26"
  updated: "2026-09-26"
---

# Hyperlocal Campaigns

A campaign sends each contact their own personalized creative over WhatsApp
or Facebook. Preparing one spends credits but sends nothing; **sending
messages real people and can't be undone**, so it always needs the user's
explicit yes. Each script prints **one line of JSON**.

## Step 0: Check access

```bash
python3 scripts/check_access.py
```

`ready`/`unknown`: continue. `blocked`: stop and tell the user which steps
their key can't do (sending needs a role allowed to update broadcasts).

## The flow

```
- [ ] 1. Audience     (⏸ who: groups, states, zones, areas)
- [ ] 2. Templates    (⏸ which creative and message template)
- [ ] 3. Plan         → reach and credits, shown to the user
- [ ] 4. Prepare      (⏸ yes to the credits) → creatives made, nothing sent
- [ ] 5. Send         (⏸ explicit yes: now, or at a time)
- [ ] 6. Status       (whenever asked)
```

### 1. Audience ⏸

```bash
python3 scripts/audience.py --groups
python3 scripts/audience.py --places states            # or zones / areas [--state S]
python3 scripts/audience.py --contacts --state Maharashtra [--search "Pune"]
```

Only names and counts come back. Use names exactly.

### 2. Templates ⏸

```bash
python3 scripts/templates.py
```

A **creative** template (the image each contact gets) plus, per channel, a
message template. WhatsApp templates must be Meta-approved (`status`); offer
only approved ones.

### 3. Plan

```bash
python3 scripts/plan.py --template "<creative>" --channel whatsapp --state Maharashtra [--group "<group>"]
```

Show `contacts` and `credits` (creatives + sending = total). Nothing is created.

### 4. Prepare ⏸

After a yes to the credits:

```bash
python3 scripts/prepare.py --title "Diwali offer" --template "<creative>" --channel whatsapp \
  --whatsapp-template "<approved template>" --state Maharashtra
```

Waits while creatives are made; ends `ready_to_send` with a `campaign` id
(keep it, don't show it). Running it again reconnects to the same campaign.

### 5. Send ⏸

Only after the user explicitly says to send (restate who and how many):

```bash
python3 scripts/send.py --campaign <campaign> --now --confirm-send
python3 scripts/send.py --campaign <campaign> --at "2026-10-01 10:00" --timezone Asia/Kolkata --confirm-send
python3 scripts/send.py --campaign <campaign> --pause | --resume | --stop | --unschedule
```

`--stop` is final. Never add `--confirm-send` without that yes.

### 6. Status

```bash
python3 scripts/status.py --campaign <campaign>
```

Report status and, per channel, sent / delivered / read / failed.

## Rules

- **Never send without an explicit yes** to this campaign, audience and time.
- **Show names and counts, never ids or contact details.**
- **Ask before spending credits** (prepare).

## When something fails

Failures print `{"status": "failed", "error": {"code", "message", "retryable"}}`.
`AUDIENCE_NEEDED`, `TEMPLATE_NEEDED`, `CONFIRMATION_NEEDED`: ask `error.ask`.
`NAME_UNKNOWN`: use a name the lists printed.

| Exit | Meaning | Tell the user |
|---|---|---|
| 2 | API key not set | Show the setup lines the script printed |
| 3 | Key rejected or not allowed | Their Vitra admin must allow Hyperlocal for their role |
| 4 | API error, or a question | Ask the question, or explain the message |
