# Contributing

## Setup

```bash
npm install
npm run check        # validate + build, the same as CI
```

Node 22+. The skills' own scripts need Python 3.10+.

## Changing a skill

- Edit files under `<name>/`. Keep `SKILL.md` short (under 500 lines);
  put detail in `references/` and link every reference from `SKILL.md`, or the
  agent never reads it.
- Bump `metadata.version` in that skill's `SKILL.md` whenever you change what
  the skill does. Installed copies are compared against it.
- Shared HTTP and auth helpers live in `_lib/`. Edit them there, then run
  `./sync-lib.sh` to copy them into every skill. Each skill must stay a
  self-contained folder, so the helpers are copied, never symlinked.
- A skill that calls a new or changed Vitra API ships only after that API is
  live in production.

## Adding a skill

1. Create `<name>/SKILL.md` at the repo root. `name` must match the folder (lowercase,
   digits and single hyphens). Write the description for the agent: what the
   skill does, when to use it, and what it is not for (at most 1024 characters).
2. Add `metadata` for the Skill Library: `skill-author`, `version`,
   `display-name`, `category`, `tags`, `source`, `added` (all quoted strings).
3. Add `listing.yaml` for the skill's page: `about`, `when-to-use`, `features`,
   `use-cases`, and `mcp-tools` (Vitra MCP tools that do the same jobs).
4. Add `README.md` for people, and `.env.sample` if the skill reads a key.
5. If it uses the shared helpers, add its targets to `sync-lib.sh`.
6. Add `./<name>` to `skills` in `.claude-plugin/plugin.json`.
7. `npm run check`.

## Releasing

Merging to `main` publishes the catalog to GitHub Pages. Bump `VERSION` and the
four plugin manifests together for a release that changes what the plugin
installs; `npm run validate` fails if they disagree.
