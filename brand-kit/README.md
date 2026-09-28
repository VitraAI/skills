# brand-kit

An agent skill that manages your organization's brand kits in Vitra Universe
(colors, fonts, tone of voice, visual style and logo): read a brand from its
website, images or brand book, save it, and edit or remove kits by name.
Vitra's image creator uses these kits to stay on brand.

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
python3 scripts/brand_kits.py list
```

Python 3.10+, standard library only.
