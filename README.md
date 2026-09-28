# Vitra skills

Agent skills that let an AI assistant (Claude Code, claude.ai, Cursor, Codex
and other Agent Skills–compatible tools) work in your Vitra organization:
images, documents, video, voice, translation memory, quality, campaigns,
workflows, projects and more.

Each skill is a top-level folder that follows the open
[Agent Skills](https://agentskills.io) format: a `SKILL.md` the agent reads,
plus the scripts it runs.

| Skill | What it does |
| --- | --- |
| [`vitra`](vitra/) | Drive files and folders, work folders, credits and quotes, saved knowledge, design-plugin jobs, any other Vitra tool |
| [`image-creator`](image-creator/) | Generate images from a prompt, edit them in plain language, multi-format briefs, save them to your Drive |
| [`image-resize`](image-resize/) | Re-compose one image for other sizes (Story, LinkedIn, 1080x1920…) |
| [`image-translation`](image-translation/) | Translate the text baked into an image and keep its layout; fix lines, objects and logos |
| [`translate-video`](translate-video/) | Dub a video, make subtitles, translate SRT/VTT files; review line by line, export or burn in |
| [`document-translation`](document-translation/) | Translate files, batches or Drive folders, formatting kept; review, proofread, back-translate and score them |
| [`dita-translation`](dita-translation/) | Follow, retry, score and download DITA map translations, one zip per language |
| [`translation-memory`](translation-memory/) | Memories, glossaries, term bases and style guides; translate strings memory-first |
| [`translation-quality`](translation-quality/) | Score a translation line by line and explain the worst lines |
| [`content-compliance`](content-compliance/) | Check text, images, audio and video against each market's rules; fix flagged images; manage markets |
| [`text-to-speech`](text-to-speech/) | Turn text into speech in catalog or cloned voices |
| [`voice-cloning`](voice-cloning/) | Clone a voice from samples, with consent |
| [`lip-sync`](lip-sync/) | Make a video's lips match a new audio track, with consent |
| [`hyperlocal-campaigns`](hyperlocal-campaigns/) | Personalized WhatsApp and Facebook campaigns to your contact network |
| [`workflows`](workflows/) | Run, follow and build your organization's Cosmos workflows; relay approvals |
| [`brand-kit`](brand-kit/) | Draft a brand kit from a website, images or brand book; edit kits by name |
| [`projects`](projects/) | Projects, tasks, checklists and job assignments, by name |
| [`prompts-library`](prompts-library/) | Find, fill, save and version the team's prompts |

## How the skills work

Every Vitra feature is a tool on the Vitra server, the same tools the Vitra MCP
connector offers. A skill is a short guide through those tools: its
`scripts/vitra.py` forwards each call to the server (`/v1/agent/tools`) and
`scripts/login.py` signs the machine in. No skill carries its own API logic, so
a server change reaches every skill at once.

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

## Sign in

The first time a skill needs Vitra, the agent asks to sign you in. It runs
`scripts/login.py`, which opens Vitra in your browser: sign in, pick the
organization, done. That machine then acts in that organization with your own
role, and stays signed in while you keep using it (30 days idle ends it). It is
the same sign-in the Vitra MCP connector uses.

```bash
python3 <skill>/scripts/login.py            # sign in
python3 <skill>/scripts/login.py --status   # who, in which organization
python3 <skill>/scripts/login.py --logout   # sign this machine out
```

### No browser? Use an API key

On a server, container or CI runner, use an organization API key instead:

1. An organization owner or admin creates a key in Vitra under Settings → API
   keys. It starts with `uvk_`, works in that one organization, and can do
   exactly what the person who created it can do there, so share it only with
   people who should have that access.
2. Make it available to the agent:

   ```bash
   export VITRA_UNIVERSE_API_KEY=uvk_your_key_here
   ```

   Set it where the agent runs, not only in your terminal. Each skill also reads
   a `.env` file in its own folder. When a key is set it is used over a sign-in.

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
