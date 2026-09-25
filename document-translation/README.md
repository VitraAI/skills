# document-translation

An agent skill that translates documents and text with the Vitra Universe API,
keeping layout and formatting: Word, PowerPoint, Excel, CSV, PDF, HTML, JSON,
XML, XLIFF and plain text, into several languages in one go, through your
organization's translation memory.

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
