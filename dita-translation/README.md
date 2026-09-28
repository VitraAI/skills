# dita-translation

An agent skill that translates DITA maps with the Vitra Universe API: upload
the map as a .zip (maps, topics and SVG images) and get back one translated
zip per language, with tags, folders and file names kept, through your
organization's translation memory. Failed topics can be retried, and each
language can be scored with a quality report whose fixes are written back
into the map.

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
python3 scripts/list_tms.py
```

Python 3.10+, standard library only.
