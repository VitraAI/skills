# Contributing

## Setup

```bash
npm install
npm run check        # validate + build, the same as CI
```

Node 22+. The skills' own scripts need Python 3.10+.

## How every skill is structured

Skills are used by many agents and many models, small ones included, so they
share one shape. Copy `video-dubbing` when in doubt.

**`SKILL.md`** (under ~200 lines, detail in `references/`):

1. Frontmatter: `description` in the third person says what the skill does,
   when to use it (with the phrases users actually say), and what it is not for.
2. One paragraph: what it produces, and "every script prints one JSON line".
3. **Step 0: Check access** with `scripts/check_access.py` (what to do on
   `ready`, `partial`, `blocked`, `unknown`).
4. **Inputs** as a table: input, required, how to get it.
5. **The flow** as a copyable checklist, then one short section per step: the
   command, what it returns, what to do next. Every place the flow stops for
   the user is marked ⏸ and says exactly what to show and what to ask.
6. **Rules**: at most ~6, each with the reason, so the model can apply it.
7. **When something fails**: the failure JSON and a short exit-code table.
8. **More detail**: every reference, each with when to read it.

**Scripts** (Python standard library only):

- Print exactly one JSON line on stdout; progress goes to stderr. Failures print
  `{"status": "failed", "error": {"code", "message", "retryable"}}`.
- Carry the decisions small models get wrong: `next_action` (what to run next),
  `checkpoint`/`error.ask` (what to ask the user), `suggestions` (next steps
  computed from the data, each marked `spends_credits`), `progress` (the
  webapp's own steps and percentages for long jobs).
- Wait for their own jobs with backoff; re-running a command reconciles instead
  of starting a job twice.
- Upload through the Vitra API host only, never straight to storage: sandboxed
  agents can often reach only the API host.
- `check_access.py` lists every step with the permissions its API calls
  require, marking optional extras.
- Scripts print curated fields only, never a raw API response, and never an
  id meant for people: agents show names, languages and line numbers.

**Tests**: `tests/<skill>/` (outside the skill, never shipped) runs the real
scripts against a local fake API. `npm test` runs them all; CI runs it on every
pull request.

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
   `use-cases`; `mcp-toolset` and `mcp-tools` (the Vitra MCP tools that do the
   same jobs, named exactly as in `scripts/mcp-tools.json`); and
   `related-skills` (each `name` + `why`: the skills people move on to from
   this one). `npm run validate` rejects a tool or skill that doesn't exist.
   When the MCP server adds or renames a tool, update `scripts/mcp-tools.json`.
4. Add `README.md` for people, and `.env.sample` if the skill reads a key.
5. If it uses the shared helpers, add its targets to `sync-lib.sh`.
6. Add `./<name>` to `skills` in `.claude-plugin/plugin.json`.
7. `npm run check`.

## Releasing

Merging to `main` publishes the catalog to GitHub Pages. Bump `VERSION` and the
four plugin manifests together for a release that changes what the plugin
installs; `npm run validate` fails if they disagree.
