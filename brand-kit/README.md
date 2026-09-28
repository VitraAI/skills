# brand-kit

Brand Kit: an agent skill for Vitra Universe. Manages the organization's brand kits in Vitra Universe: the colors, fonts, tone of voice, visual style and logo that Vitra's image tools apply to stay on brand. Drafts a brand from its website, product images or a brand-book PDF, saves it as a kit, and lists, shows, edits or deletes kits by name.

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
