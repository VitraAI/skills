// The page people see at the Pages root: what the skills are and how to
// install them. Rendered from the same catalog as catalog.json, so the two can
// never disagree. Plain HTML and inline CSS: no scripts, fonts or other hosts.

const esc = (s) =>
  String(s).replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

/** The description's first sentence: the rest is written for the agent. */
const summary = (d) => /^([\s\S]+?[.!?])(\s|$)/.exec(d)?.[1] ?? d;

export function renderLanding({ version, skills, repo }) {
  const github = `https://github.com/${repo}`;
  const cards = skills
    .map(
      (s) => `
      <li class="skill">
        <div class="skill-head">
          <h3>${esc(s.displayName)}</h3>
          <span class="tag">${esc(s.category)}</span>
          <span class="ver">v${esc(s.version)}</span>
        </div>
        <p>${esc(summary(s.description))}</p>
        <pre><code>npx skills add ${esc(repo)} --skill ${esc(s.name)}</code></pre>
        <div class="links">
          <a href="downloads/${esc(s.name)}.zip">Download zip</a>
          <a href="${github}/tree/main/${esc(s.name)}">Source</a>
        </div>
      </li>`,
    )
    .join('');

  return `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Vitra skills</title>
<meta name="description" content="Agent skills for Vitra Universe: images, image translation and video dubbing, for Claude Code, claude.ai, Cursor, Codex and other agents.">
<style>
  :root {
    color-scheme: light;
    --bg: #f7f6fb; --card: #ffffff; --ink: #1b1830; --ink-2: #4a4662; --ink-3: #7b7792;
    --line: #e3e0ee; --code: #f1eff8; --accent: #6d35e8; --wash: #efe8ff;
  }
  @media (prefers-color-scheme: dark) {
    :root {
      color-scheme: dark;
      --bg: #13111d; --card: #1b1829; --ink: #efedf7; --ink-2: #c3bfd6; --ink-3: #8f8aa8;
      --line: #322d48; --code: #242036; --accent: #a98bff; --wash: #2b2346;
    }
  }
  * { box-sizing: border-box; }
  body { margin: 0; background: var(--bg); color: var(--ink);
    font: 15px/1.6 ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
    padding: 40px 16px 64px; }
  main { max-width: 880px; margin: 0 auto; display: flex; flex-direction: column; gap: 36px; }
  h1, h2, h3 { margin: 0; line-height: 1.25; text-wrap: balance; }
  h1 { font-size: 32px; letter-spacing: -0.01em; }
  h2 { font-size: 18px; }
  h3 { font-size: 16px; }
  p { margin: 0; color: var(--ink-2); max-width: 68ch; }
  a { color: var(--accent); }
  code, pre { font: 13px/1.6 ui-monospace, SFMono-Regular, Menlo, monospace; }
  pre { margin: 0; background: var(--code); border: 1px solid var(--line); border-radius: 8px;
    padding: 10px 12px; color: var(--ink);
    white-space: pre-wrap; overflow-wrap: anywhere; }
  header { display: flex; flex-direction: column; gap: 10px; }
  .eyebrow { font-size: 12px; font-weight: 600; letter-spacing: .08em; text-transform: uppercase; color: var(--accent); }
  section { display: flex; flex-direction: column; gap: 12px; }
  .install { display: grid; gap: 12px; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); }
  .box { background: var(--card); border: 1px solid var(--line); border-radius: 12px; padding: 16px;
    display: flex; flex-direction: column; gap: 8px; }
  .box h3 { font-size: 14px; }
  .box p { font-size: 13px; }
  ul.skills { list-style: none; margin: 0; padding: 0; display: grid; gap: 12px;
    grid-template-columns: repeat(auto-fit, minmax(300px, 1fr)); }
  .skill { background: var(--card); border: 1px solid var(--line); border-radius: 14px; padding: 16px;
    display: flex; flex-direction: column; gap: 10px; min-width: 0; }
  .skill-head { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
  .tag { font-size: 12px; background: var(--wash); color: var(--accent); padding: 1px 8px; border-radius: 999px; }
  .ver { font-size: 12px; color: var(--ink-3); margin-left: auto; font-variant-numeric: tabular-nums; }
  .skill p { font-size: 14px; }
  .links { display: flex; gap: 16px; font-size: 14px; margin-top: auto; }
  footer { color: var(--ink-3); font-size: 13px; display: flex; gap: 16px; flex-wrap: wrap; }
  footer a { color: var(--ink-2); }
</style>
</head>
<body>
<main>
  <header>
    <span class="eyebrow">Vitra.ai</span>
    <h1>Vitra skills</h1>
    <p>Agent skills that let your AI assistant work in your Vitra organization: generate and edit images, translate the text in images, adapt images to other sizes, and dub videos into other languages. They follow the open Agent Skills format, so they work in Claude Code, claude.ai, Cursor, Codex and other compatible agents.</p>
  </header>

  <section aria-labelledby="install">
    <h2 id="install">Install</h2>
    <div class="install">
      <div class="box">
        <h3>Any agent</h3>
        <pre><code>npx skills add ${esc(repo)}</code></pre>
      </div>
      <div class="box">
        <h3>Claude Code plugin</h3>
        <pre><code>/plugin marketplace add ${esc(repo)}
/plugin install vitra@vitra</code></pre>
      </div>
      <div class="box">
        <h3>claude.ai</h3>
        <p>Download a skill's zip below, then Settings → Capabilities → Skills → Upload skill.</p>
      </div>
    </div>
    <p>Every skill needs an organization API key. An owner or admin creates one in Vitra under Settings → API keys; then set <code>VITRA_UNIVERSE_API_KEY</code> where your agent runs.</p>
  </section>

  <section aria-labelledby="skills">
    <h2 id="skills">Skills</h2>
    <ul class="skills">${cards}
    </ul>
  </section>

  <footer>
    <a href="${github}">GitHub</a>
    <a href="https://universe.vitra.ai/skills">Skill Library in Vitra</a>
    <a href="catalog.json">catalog.json</a>
    <a href=".well-known/agent-skills/index.json">Discovery index</a>
    <span>Catalog ${esc(version)}</span>
  </footer>
</main>
</body>
</html>
`;
}
