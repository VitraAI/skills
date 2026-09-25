# Vitra skills: notes for agents working in this repo

Public repo of Agent Skills for Vitra Universe. Customers install from here;
the Vitra webapp's Skill Library reads the catalog this repo publishes.

## Layout

- `<name>/` at the root: one self-contained skill each (SKILL.md, README.md,
  listing.yaml, scripts/, references/, .env.sample). Same layout as the
  server repo's old `skills/` folder.
- `_lib/`: shared Python helpers, copied into skills by `sync-lib.sh`.
- `pack-skill.sh <name>`: zip one skill into `.builds/` by hand.
- `scripts/catalog.mjs`: reads the skills (the single parser).
  `validate.mjs` checks them, `build.mjs` writes `dist/`.
- `.claude-plugin/`, `.codex-plugin/`, `.cursor-plugin/`: plugin manifests.
  `.mcp.json`: the Vitra MCP server the plugin adds.

## Rules

- Follow the Agent Skills spec: `name` = folder, description ≤ 1024 chars,
  compatibility ≤ 500, metadata values are strings, SKILL.md body < 500 lines.
- Never symlink into a skill; vendor with `sync-lib.sh`. Never commit `.env`.
- Scripts use the Python standard library only.
- `listing.yaml` is page copy for the Skill Library; it is not part of the skill
  and is left out of every archive.
- Run `npm run check` before proposing a change.

## Relationship to the server

- The server (`universe-server`) provides the `/v1` routes these skills call and
  the Vitra MCP tools. It stores no skills; its `AGENT-SURFACES.md` has the
  shared rules and plan.
- A skill ships only after every route it calls is live in **production**
  (`https://universe-api.vitra.ai`, the scripts' default base URL). Test against
  a devbox with `VITRA_UNIVERSE_BASE_URL`.
- `listing.yaml` → `mcp-tools` must name tools the server's MCP registry offers
  (`buildRegistry()` in `src/core/mcp/mcp.registry.ts`); copy each `title` from there.
- When the server changes a route a skill calls, update the skill in step and
  bump its `version`.
