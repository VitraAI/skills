# translation-memory

An agent skill for your organization's translation memory in Vitra Universe:
translate short texts memory-first, look up and correct approved wording,
import TMX/XLIFF/Excel/CSV translations, create memories, and read glossaries
and style guides.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key, created in the Vitra webapp under
Settings → API keys) in the agent's environment, or in a `.env` beside
`SKILL.md` (`cp .env.sample .env`). Never commit `.env`.

```bash
python3 scripts/check_access.py
python3 scripts/list_tms.py
```

Python 3.10+, standard library only.
