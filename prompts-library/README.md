# prompts-library

An agent skill for your organization's prompt library in Vitra Universe: find
a saved prompt, fill in its variables and use it; save your own prompts,
private or shared with the team; edit them with full version history.

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
python3 scripts/prompts.py list
```

Python 3.10+, standard library only.
