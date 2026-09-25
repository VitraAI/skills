# hyperlocal-campaigns

An agent skill for Vitra Hyperlocal: pick an audience of retailers or partners,
estimate reach and cost, prepare a personalized creative for each contact, and
— only with an explicit yes — send it over WhatsApp or Facebook, now or on a
schedule, then track delivery.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key, created in the Vitra webapp under
Settings → API keys) in the agent's environment, or in a `.env` beside
`SKILL.md` (`cp .env.sample .env`). Never commit `.env`. The organization needs
Hyperlocal and a connected WhatsApp or Facebook account.

```bash
python3 scripts/check_access.py
python3 scripts/templates.py
```

Python 3.10+, standard library only.
