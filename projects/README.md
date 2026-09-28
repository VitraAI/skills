# projects

An agent skill that runs your organization's projects and tasks in Vitra
Universe: see what's in flight and what's due, create and update projects,
add people, and create, move, assign and delete tasks, all by name.

Drop this folder into your agent's skills directory; the agent reads
`SKILL.md` and runs the scripts itself.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key for one Vitra organization) in the
environment the agent runs in, or put it in a `.env` beside `SKILL.md`
(`cp .env.sample .env`). Keys are created in the Vitra webapp under
Settings → API keys. Never commit `.env`.

## Verify it works

```bash
python3 scripts/check_access.py
python3 scripts/projects.py list
```

Python 3.10+, standard library only.
