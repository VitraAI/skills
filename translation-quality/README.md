# translation-quality

An agent skill that scores translations line by line with the Vitra Universe API — accuracy, fluency, terminology, style — and explains the worst lines.

Drop this folder into your agent's skills directory; the agent reads
`SKILL.md` and runs the scripts itself.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key, created in the Vitra webapp under
Settings → API keys) in the agent's environment, or in a `.env` beside
`SKILL.md` (`cp .env.sample .env`). Never commit `.env`.

```bash
python3 scripts/check_access.py
python3 scripts/list_tms.py
```

Python 3.10+, standard library only.
