# workflows

An agent skill that runs your organization's Vitra Cosmos workflows — chains of
translation, dubbing, checking and publishing steps — with their inputs,
follows each run, and relays your approvals.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key, created in the Vitra webapp under
Settings → API keys) in the agent's environment, or in a `.env` beside
`SKILL.md` (`cp .env.sample .env`). Never commit `.env`.

```bash
python3 scripts/check_access.py
python3 scripts/list_flows.py
```

Python 3.10+, standard library only.
