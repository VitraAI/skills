# Installing the Vitra skills

Every method installs the same folders. Pick the one your agent supports.

## `npx skills` (recommended)

Works with Claude Code, Cursor, Codex and 70+ other agents. Needs Node.js.

```bash
npx skills add VitraAI/skills                         # all skills, pick your agents
npx skills add VitraAI/skills --skill image-creator   # one skill
```

Or from the published catalog instead of GitHub:

```bash
npx skills add https://vitraai.github.io/skills
```

## Claude Code plugin

```
/plugin marketplace add VitraAI/skills
/plugin install vitra@vitra
```

The plugin also adds the Vitra MCP server. The first time Claude Code uses it,
it asks you to sign in to Vitra and pick an organization.

## GitHub CLI

```bash
gh skill install VitraAI/skills
```

## claude.ai

1. Download the skill's zip from the Skill Library in Vitra, or from
   `https://vitraai.github.io/skills/downloads/<skill>.zip`.
2. Settings → Capabilities → Skills → Upload skill, and pick the zip.

## By hand

```bash
git clone --depth 1 https://github.com/VitraAI/skills.git
cp -R skills/image-creator ~/.claude/skills/
```

## Your API key

Every method needs `VITRA_UNIVERSE_API_KEY`; see [README](README.md#set-up-your-key).

## Updating

| Installed with | Update with |
| --- | --- |
| `npx skills` | run the same `npx skills add` again |
| Claude Code plugin | `/plugin update vitra@vitra` |
| `gh skill install` | `gh skill update VitraAI/skills` |
| zip or by hand | download or copy the new version over the old one |
