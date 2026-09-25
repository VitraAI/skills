// CI checks for every pull request. Exits 1 with one line per problem.
//
// - Each SKILL.md follows the Agent Skills spec (see catalog.mjs), and its
//   listing.yaml, if any, is well formed.
// - Every skill is self-contained: every reference file is linked from
//   SKILL.md and every link resolves, nothing reaches outside the folder with ../,
//   and git would commit no .env file.
// - Every plugin manifest carries the repo's VERSION, and the Claude Code
//   plugin lists every skill folder.

import { execFileSync } from 'node:child_process';
import { existsSync, readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { loadSkills } from './catalog.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const problems = [];
const report = (where, what) => problems.push(`${where}: ${what}`);

const results = loadSkills(ROOT);
for (const { folder, skill, problems: found } of results) {
  const where = folder;
  for (const p of found) report(where, p);
  if (!skill) continue;

  const paths = new Set(skill.files.map((f) => f.path));
  const body = readFileSync(join(skill.dir, 'SKILL.md'), 'utf8');

  // Every references/*.md that SKILL.md names exists.
  for (const ref of new Set(body.match(/references\/[A-Za-z0-9_./-]+\.md/g) ?? [])) {
    if (!paths.has(ref)) report(where, `SKILL.md links ${ref}, which does not exist`);
  }
  // An unlinked reference is never read by the agent: link it or drop it.
  for (const p of paths) {
    if (/^references\/[^/]+\.md$/.test(p) && !body.includes(p.slice('references/'.length))) {
      report(where, `${p} is not linked from SKILL.md, so agents never read it`);
    }
  }
  // Installed skills live alone in an agent's skills folder.
  if (/(^|[^./])\.\.\//m.test(body)) report(where, 'SKILL.md reaches outside the skill with ../');
}

// A stray secret must never reach a public repo. Check what git would commit
// (tracked + staged); a local, gitignored .env beside a skill is how the
// skills are meant to be configured, so its presence on disk is fine.
let committed;
try {
  committed = execFileSync('git', ['ls-files', '-z', '--cached', '--others', '--exclude-standard'], {
    cwd: ROOT,
    encoding: 'utf8',
  })
    .split('\0')
    .filter(Boolean);
} catch {
  committed = null; // not a git checkout (e.g. an exported tree): nothing to commit
}
for (const f of committed ?? []) {
  const base = f.split('/').pop();
  if (base === '.env' || (base.startsWith('.env.') && base !== '.env.sample')) {
    report(f, 'would be committed; secrets belong in a gitignored .env');
  }
}

// Manifests agree with VERSION.
const version = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim();
if (!/^\d+\.\d+\.\d+$/.test(version)) report('VERSION', `"${version}" is not x.y.z`);
const manifests = {
  '.claude-plugin/plugin.json': (m) => m.version,
  '.claude-plugin/marketplace.json': (m) => m.plugins?.[0]?.version,
  '.codex-plugin/plugin.json': (m) => m.version,
  '.cursor-plugin/plugin.json': (m) => m.version,
};
for (const [file, pick] of Object.entries(manifests)) {
  const full = join(ROOT, file);
  if (!existsSync(full)) {
    report(file, 'missing');
    continue;
  }
  const v = pick(JSON.parse(readFileSync(full, 'utf8')));
  if (v !== version) report(file, `version ${v} does not match VERSION ${version}`);
}

// The Claude Code plugin names its skill folders explicitly (they sit at the
// repo root, not in skills/), so a new skill must be added there too.
const listed = JSON.parse(readFileSync(join(ROOT, '.claude-plugin/plugin.json'), 'utf8')).skills ?? [];
const folders = results.map((r) => `./${r.folder}`);
for (const f of folders) {
  if (!listed.includes(f)) report('.claude-plugin/plugin.json', `skills does not list ${f}`);
}
for (const l of listed) {
  if (!folders.includes(l)) report('.claude-plugin/plugin.json', `skills lists ${l}, which is not a skill folder`);
}

if (problems.length) {
  console.error(problems.join('\n'));
  console.error(`\n${problems.length} problem(s).`);
  process.exit(1);
}
console.log(`✓ ${results.length} skills valid, manifests at ${version}`);
