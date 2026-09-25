# lip-sync

An agent skill that makes the lips in a video match a new audio track with the Vitra Universe API and saves the rendered video.

Drop this folder into your agent's skills directory; the agent reads
`SKILL.md` and runs the scripts itself.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key, created in the Vitra webapp under
Settings → API keys) in the agent's environment, or in a `.env` beside
`SKILL.md` (`cp .env.sample .env`). Never commit `.env`.

```bash
python3 scripts/check_access.py
python3 scripts/list_lip_sync_models.py
```

Python 3.10+, standard library only.
