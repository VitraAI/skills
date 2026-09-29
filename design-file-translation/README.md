# design-file-translation

Design File Translation: an agent skill for Vitra Universe. Follows and finishes translations sent to Vitra Universe from the design-tool and office plugins (Figma, Canva, Adobe and Word): lists the jobs with their languages and review status, reads a job line by line, corrects, verifies or approves lines, syncs edits with the translation memory, renames a job or files it in a work folder, suggests creative alternatives for a line, scores a language with a quality report and writes its fixes back.

Drop this folder into your agent's skills directory. The agent reads `SKILL.md`
and does the rest; you don't run anything by hand.

## How it works

Every step is a Vitra server tool (the same tools the Vitra MCP connector
offers). The skill only guides the agent through them:

- `scripts/vitra.py` forwards each call to the tools route of the Vitra API
  (`/v1/agent/tools`) and prints one JSON object. `tools`, `describe`, `call`,
  `upload` and `download` are its commands.
- `scripts/login.py` signs this machine in to one Vitra organization.

Anything that spends credits is priced first and needs your yes.

## Sign in

```bash
python3 scripts/login.py            # opens the browser: sign in, pick the organization
python3 scripts/login.py --status   # who is signed in, where
python3 scripts/login.py --logout
```

No browser (a server, a container)? An organization owner or admin creates an
API key in Vitra under Settings -> API keys; set it where the agent runs:

```bash
export VITRA_UNIVERSE_API_KEY=uvk_your_key_here
```

The key acts with its creator's role in that one organization. Keep it secret.

## Requirements

Python 3.10+, standard library only. Outbound HTTPS to the Vitra API.
