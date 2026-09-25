// Build what GitHub Pages serves, into dist/:
//
//   catalog.json                         Skill Library grid: summaries + facets
//   skills/<name>.json                   one skill's page (listing, README, files)
//   downloads/<name>.zip                 skill folder zipped as <name>/..., for
//                                        claude.ai "Upload skill" and manual unzip
//   .well-known/agent-skills/index.json  Agent Skills discovery index, so
//   .well-known/agent-skills/<name>.zip  `npx skills add https://<pages host>` works;
//                                        SKILL.md at the archive root, per the spec
//
//   index.html                           landing page: the skills and how to install them
//
// Byte-for-byte reproducible: sorted files, fixed timestamps, no build time in
// the output. Usage: node scripts/build.mjs [outDir]

import { createHash } from 'node:crypto';
import { mkdirSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import JSZip from 'jszip';

import { loadSkills, toDetail, toSummary } from './catalog.mjs';
import { renderLanding } from './landing.mjs';

const ROOT = join(dirname(fileURLToPath(import.meta.url)), '..');
const OUT = join(ROOT, process.argv[2] ?? 'dist');
const DISCOVERY_SCHEMA = 'https://schemas.agentskills.io/discovery/0.2.0/schema.json';
const FIXED_DATE = new Date('2000-01-01T00:00:00Z');

const results = loadSkills(ROOT);
const broken = results.filter((r) => !r.skill || r.problems.length);
if (broken.length) {
  for (const r of broken) console.error(`${r.folder}: ${r.problems.join('; ')}`);
  console.error('\nRun `npm run validate` and fix the skills above before building.');
  process.exit(1);
}
const skills = results.map((r) => r.skill);

/** Zip a skill; `prefix` is '<name>/' for the download, '' for discovery. */
async function zipSkill(skill, prefix) {
  const zip = new JSZip();
  // Folder entries too get the fixed date: left to JSZip they carry the build
  // time, and the archive (and its published digest) would change every build.
  const dirs = new Set(prefix ? [prefix.slice(0, -1)] : []);
  for (const file of skill.files) {
    const parts = (prefix + file.path).split('/').slice(0, -1);
    for (let i = 1; i <= parts.length; i += 1) dirs.add(parts.slice(0, i).join('/'));
  }
  for (const dir of [...dirs].sort()) {
    zip.file(dir, null, { dir: true, date: FIXED_DATE, unixPermissions: 0o40775 });
  }
  for (const file of skill.files) {
    zip.file(prefix + file.path, readFileSync(join(skill.dir, file.path)), {
      unixPermissions: file.mode,
      date: FIXED_DATE,
      createFolders: false,
    });
  }
  return zip.generateAsync({ type: 'nodebuffer', compression: 'DEFLATE', platform: 'UNIX' });
}

const sha256 = (buf) => `sha256:${createHash('sha256').update(buf).digest('hex')}`;

function write(rel, data) {
  const full = join(OUT, rel);
  mkdirSync(dirname(full), { recursive: true });
  writeFileSync(full, data);
}
const json = (value) => JSON.stringify(value, null, 2) + '\n';

function facets(summaries, key) {
  const counts = new Map();
  for (const s of summaries) counts.set(s[key], (counts.get(s[key]) ?? 0) + 1);
  return [...counts.entries()]
    .sort(([a], [b]) => (a < b ? -1 : a > b ? 1 : 0))
    .map(([name, count]) => ({ name, count }));
}

rmSync(OUT, { recursive: true, force: true });

const summaries = skills.map(toSummary);
const version = readFileSync(join(ROOT, 'VERSION'), 'utf8').trim();
write(
  'catalog.json',
  json({
    version,
    skills: summaries,
    categories: facets(summaries, 'category'),
    sources: facets(summaries, 'source'),
  }),
);

const index = [];
for (const skill of skills) {
  write(`skills/${skill.name}.json`, json(toDetail(skill)));
  write(`downloads/${skill.name}.zip`, await zipSkill(skill, `${skill.name}/`));

  const flat = await zipSkill(skill, '');
  write(`.well-known/agent-skills/${skill.name}.zip`, flat);
  index.push({
    name: skill.name,
    type: 'archive',
    description: skill.description,
    url: `${skill.name}.zip`,
    digest: sha256(flat),
  });
  console.log(`  ${skill.name} ${skill.version}  ${skill.files.length} files`);
}
write('.well-known/agent-skills/index.json', json({ $schema: DISCOVERY_SCHEMA, skills: index }));

// The repo slug install commands name, from the plugin manifest's repository.
const repo = JSON.parse(readFileSync(join(ROOT, '.claude-plugin/plugin.json'), 'utf8'))
  .repository.replace(/^https:\/\/github\.com\//, '');
write('index.html', renderLanding({ version, skills: summaries, repo }));

write('VERSION', version + '\n');
// Pages runs Jekyll by default, which drops dot-folders like .well-known.
write('.nojekyll', '');

console.log(`\nBuilt ${skills.length} skills (catalog ${version}) into ${OUT}`);
