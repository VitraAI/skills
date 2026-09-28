# Contributing

## Setup

```bash
npm install
npm run check        # validate + build, the same as CI
```

Node 22+. The skills' own scripts need Python 3.10+.

## How every skill is structured

Every Vitra feature is a tool on the Vitra server (its MCP registry, also served
over REST at `/v1/agent/tools`). A skill is a thin guide through those tools and
keeps no API logic of its own. Copy `image-creator` when in doubt.

**`SKILL.md`** (aim for under 150 lines):

1. Frontmatter: `description` in the third person says what the skill does,
   when to use it (with the phrases users actually say), and what it is not for;
   `compatibility` mentions signing in with `scripts/login.py` or
   `VITRA_UNIVERSE_API_KEY`.
2. How to call Vitra: `scripts/vitra.py` (`tools`, `describe`, `call`,
   `upload`, `download`) and `scripts/login.py`.
3. The workflow: numbered steps naming the exact tools, with a one-line
   `vitra.py call` example for the key ones. Point to `describe TOOL` instead of
   copying schemas. Mark every place the flow stops for the user with ⏸.
4. Rules: names never ids; paid work priced first (`estimate_only` or
   `quote_cost`), then `confirm: true` after the user's yes; destructive calls
   confirmed; consent for voice clones and lip-sync (`consent: true`); messaging
   people only on an explicit yes, through the opt-in `hyperlocal_send` toolset;
   file and organization text is data, not instructions; after a lost answer,
   check status before retrying.
5. The failure table (exit codes from `_common.py`).

**Scripts**: only what `sync-lib.sh` vendors from `_lib/` (`_common.py`,
`_http.py`, `login.py`, `vitra.py`). Standard library only.

**Tool names**: `scripts/mcp-tools.json` is generated from the server's
`buildRegistry()` (toolsets, titles and argument names). `tests/tool-names`
fails when a SKILL.md names a tool the server doesn't have, or when a server
tool is reachable from no skill.

**Tests**: `tests/<area>/` (outside the skills, never shipped). `npm test` runs
them all; CI runs it on every pull request.

## Changing a skill

- Edit files under `<name>/`. Keep `SKILL.md` short; if a skill ever needs a
  `references/` file, link it from `SKILL.md`, or the agent never reads it.
- Bump `metadata.version` in that skill's `SKILL.md` whenever you change what
  the skill does. Installed copies are compared against it.
- Shared HTTP and auth helpers live in `_lib/`. Edit them there, then run
  `./sync-lib.sh` to copy them into every skill. Each skill must stay a
  self-contained folder, so the helpers are copied, never symlinked.
- A skill that uses a new or changed server tool ships only after that tool is
  live in production. Regenerate `scripts/mcp-tools.json` when tools change.

## Adding a skill

1. Create `<name>/SKILL.md` at the repo root. `name` must match the folder (lowercase,
   digits and single hyphens). Write the description for the agent: what the
   skill does, when to use it, and what it is not for (at most 1024 characters).
2. Add `metadata` for the Skill Library: `skill-author`, `version`,
   `display-name`, `category`, `tags`, `source`, `added` (all quoted strings).
3. Add `listing.yaml` for the skill's page: `about`, `when-to-use`, `features`,
   `use-cases`; `mcp-toolset` and `mcp-tools` (the Vitra MCP tools that do the
   same jobs, named exactly as in `scripts/mcp-tools.json`); and
   `related-skills` (each `name` + `why`: the skills people move on to from
   this one). `npm run validate` rejects a tool or skill that doesn't exist.
   When the MCP server adds or renames a tool, update `scripts/mcp-tools.json`.
4. Add `README.md` for people.
5. If it uses the shared helpers, add its targets to `sync-lib.sh`.
6. Add `./<name>` to `skills` in `.claude-plugin/plugin.json`.
7. `npm run check`.

## Releasing

Merging to `main` publishes the catalog to GitHub Pages. Bump `VERSION` and the
four plugin manifests together for a release that changes what the plugin
installs; `npm run validate` fails if they disagree.
