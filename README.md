# Vitra skills

Agent skills that let an AI assistant (Claude Code, claude.ai, Cursor, Codex
and other Agent Skills–compatible tools) work in your Vitra organization:
generate and edit images, translate the text in images, adapt images to other
sizes, and dub videos into other languages.

Each skill is a top-level folder that follows the open
[Agent Skills](https://agentskills.io) format: a `SKILL.md` the agent reads,
plus the scripts it runs.

| Skill | What it does |
| --- | --- |
| [`image-creator`](image-creator/) | Generate images from a prompt, edit them in plain language, save them to your Drive |
| [`image-resize`](image-resize/) | Re-compose one image for other sizes (Story, LinkedIn, 1080x1920…) |
| [`image-translation`](image-translation/) | Translate the text baked into an image and keep its layout |
| [`video-dubbing`](video-dubbing/) | Dub a video into other languages, review it line by line, export it |

## Status

Version 0.1, ahead of the production release it depends on. Until that release
is live on `universe-api.vitra.ai`:

- `image-creator` (generate, edit, save to Drive), `image-resize` and
  `image-translation` work.
- `image-creator`'s brand-kit scripts, `video-dubbing` and the Vitra MCP
  server that the Claude Code plugin adds need that release.

## Install

Any agent that supports Agent Skills:

```bash
npx skills add VitraAI/skills
```

Claude Code, as a plugin (also connects the Vitra MCP server):

```
/plugin marketplace add VitraAI/skills
/plugin install vitra@vitra
```

GitHub CLI 2.90+:

```bash
gh skill install VitraAI/skills
```

claude.ai, or by hand: download a skill's zip from the
[Skill Library](https://universe.vitra.ai/skills) and upload it in
Settings → Capabilities → Skills, or unzip it into `~/.claude/skills/`.

More options and updating: [INSTALL.md](INSTALL.md).

## Set up your key

The skills call Vitra with an organization API key.

1. An organization owner or admin creates a key in Vitra under Settings → API
   keys. It starts with `uvk_`, works in that one organization, and can do
   exactly what the person who created it can do there, so share it only with
   people who should have that access.
2. Make it available to the agent:

   ```bash
   export VITRA_UNIVERSE_API_KEY=uvk_your_key_here
   ```

   Set it where the agent runs, not only in your terminal. Each skill also reads
   a `.env` file in its own folder (copy `.env.sample`).

## How this repo is published

Every push to `main` runs the checks and publishes the catalog to GitHub Pages:

| Path | Used by |
| --- | --- |
| `catalog.json`, `skills/<name>.json` | The Skill Library page in Vitra |
| `downloads/<name>.zip` | The Skill Library's Download button, claude.ai upload |
| `.well-known/agent-skills/index.json` | `npx skills add https://<pages host>` ([discovery spec](https://github.com/cloudflare/agent-skills-discovery-rfc)) |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## License

[MIT](LICENSE)
