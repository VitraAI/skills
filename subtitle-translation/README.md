# subtitle-translation

An agent skill that translates subtitle files (SRT, VTT, ASS, SSA) with the
Vitra Universe API: one command, every language, each cue's timing kept, one
file per language in the format you choose. Lines can then be reviewed and
corrected by number.

## Setup

Set `VITRA_UNIVERSE_API_KEY` (a `uvk_` key, created in the Vitra webapp under
Settings → API keys) in the agent's environment, or in a `.env` beside
`SKILL.md` (`cp .env.sample .env`). Never commit `.env`.

```bash
python3 scripts/check_access.py
python3 scripts/list_languages.py spanish
```

Python 3.10+, standard library only.
