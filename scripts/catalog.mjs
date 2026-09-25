// Read every skill in this repo into one catalog. Shared by build.mjs and
// validate.mjs so the published catalog and the CI checks can never disagree.
//
// A skill is an Agent Skills folder at the repo root: <name>/SKILL.md plus its
// scripts and references (the same layout the server repo's skills/ had).
// Optional `metadata` keys drive the Skill Library (all
// strings, as the spec requires): display-name, category, tags
// (comma-separated), source (vitra | anthropic | internal), added and updated
// (YYYY-MM-DD), skill-author, version. The page's longer copy lives in an
// optional listing.yaml beside SKILL.md.

import { existsSync, lstatSync, readdirSync, readFileSync, statSync } from 'node:fs';
import { join, posix, relative, sep } from 'node:path';
import { parse as parseYaml } from 'yaml';

export const SKILL_SOURCES = ['vitra', 'anthropic', 'internal'];
/** Agent Skills spec: lowercase letters, digits and single hyphens. */
export const SKILL_NAME = /^[a-z0-9]+(-[a-z0-9]+)*$/;
export const LISTING_FILE = 'listing.yaml';

const FRONTMATTER = /^---\r?\n([\s\S]*?)\r?\n---\r?\n?/;
const DATE = /^\d{4}-\d{2}-\d{2}$/;

/** Never shipped: secrets, caches and build output. Same rules at any depth. */
export function isExcluded(segment) {
  return (
    segment === '.DS_Store' ||
    segment === '__pycache__' ||
    segment === '.builds' ||
    segment.endsWith('.pyc') ||
    segment === '.env' ||
    (segment.startsWith('.env.') && segment !== '.env.sample')
  );
}

/** Files that ship, sorted by code point so archives never depend on locale. */
export function listFiles(root, dir = root, out = []) {
  for (const entry of readdirSync(dir, { withFileTypes: true })) {
    if (isExcluded(entry.name)) continue;
    // Page copy for the library, not part of the skill.
    if (dir === root && entry.name === LISTING_FILE) continue;
    const full = join(dir, entry.name);
    // A symlink could point outside the skill folder: never follow one.
    if (lstatSync(full).isSymbolicLink()) continue;
    if (entry.isDirectory()) listFiles(root, full, out);
    else if (entry.isFile()) {
      const stat = statSync(full);
      out.push({
        path: relative(root, full).split(sep).join(posix.sep),
        size: stat.size,
        mode: stat.mode & 0o777,
      });
    }
  }
  return out.sort((a, b) => (a.path < b.path ? -1 : a.path > b.path ? 1 : 0));
}

function str(value) {
  if (typeof value === 'string') return value.trim() || null;
  if (typeof value === 'number') return String(value);
  return null;
}

const date = (v) => {
  const s = str(v);
  return s && DATE.test(s) ? s : null;
};

const titleCase = (name) =>
  name
    .split('-')
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(' ');

function points(value, where, problems) {
  if (value == null) return [];
  if (!Array.isArray(value)) {
    problems.push(`${where} must be a list`);
    return [];
  }
  return value.flatMap((item, i) => {
    const t = str(item?.title);
    const d = str(item?.description);
    if (!t || !d) {
      problems.push(`${where}[${i}] needs a title and a description`);
      return [];
    }
    return [{ title: t, description: d }];
  });
}

function readListing(dir, problems) {
  let text;
  try {
    text = readFileSync(join(dir, LISTING_FILE), 'utf8');
  } catch {
    return null;
  }
  let doc;
  try {
    doc = parseYaml(text);
  } catch (e) {
    problems.push(`${LISTING_FILE} is not valid YAML: ${e.message}`);
    return null;
  }
  if (!doc || typeof doc !== 'object' || Array.isArray(doc)) {
    problems.push(`${LISTING_FILE} is not a mapping`);
    return null;
  }
  const mcpTools = (Array.isArray(doc['mcp-tools']) ? doc['mcp-tools'] : []).flatMap(
    (t, i) => {
      const name = str(t?.name);
      const title = str(t?.title);
      if (!name || !/^[a-z][a-z0-9_]{1,63}$/.test(name) || !title) {
        problems.push(`mcp-tools[${i}] needs a snake_case name and a title`);
        return [];
      }
      return [{ name, title }];
    },
  );
  return {
    about: str(doc.about),
    whenToUse: str(doc['when-to-use']),
    features: points(doc.features, 'features', problems),
    useCases: points(doc['use-cases'], 'use-cases', problems),
    mcpTools,
  };
}

function readText(path) {
  try {
    return readFileSync(path, 'utf8').trim() || null;
  } catch {
    return null;
  }
}

/**
 * Parse one skill folder. `problems` collects everything wrong with it; a
 * skill with problems is still returned when it can be, so validate.mjs can
 * report every issue in one run.
 */
export function readSkill(dir, folder) {
  const problems = [];
  let text;
  try {
    text = readFileSync(join(dir, 'SKILL.md'), 'utf8');
  } catch {
    return { skill: null, problems: ['no SKILL.md'] };
  }
  const match = FRONTMATTER.exec(text);
  if (!match) return { skill: null, problems: ['SKILL.md has no frontmatter'] };

  let front;
  try {
    front = parseYaml(match[1]);
  } catch (e) {
    return { skill: null, problems: [`frontmatter is not valid YAML: ${e.message}`] };
  }
  if (!front || typeof front !== 'object') {
    return { skill: null, problems: ['frontmatter is not a mapping'] };
  }

  const name = str(front.name);
  const description = str(front.description);
  const compatibility = str(front.compatibility);
  if (!name || !SKILL_NAME.test(name) || name.length > 64) problems.push('invalid name');
  else if (name !== folder) problems.push(`name "${name}" does not match the folder`);
  if (!description) problems.push('missing description');
  else if (description.length > 1024) problems.push(`description is ${description.length} characters (max 1024)`);
  if (compatibility && compatibility.length > 500) problems.push(`compatibility is ${compatibility.length} characters (max 500)`);

  const meta = front.metadata && typeof front.metadata === 'object' ? front.metadata : {};
  for (const [k, v] of Object.entries(meta)) {
    if (typeof v !== 'string') problems.push(`metadata.${k} must be a string (quote it)`);
  }
  const version = str(meta.version);
  if (!version) problems.push('metadata.version is missing');
  const source = str(meta.source)?.toLowerCase();
  if (source && !SKILL_SOURCES.includes(source)) problems.push(`unknown source "${source}"`);

  const body = text.slice(match[0].length).trim();
  if (body.split('\n').length > 500) problems.push('SKILL.md body is over 500 lines');

  const files = listFiles(dir);
  const skill = {
    name: name ?? folder,
    displayName: str(meta['display-name']) ?? titleCase(folder),
    description: description ?? '',
    author: str(meta['skill-author']),
    version,
    category: str(meta.category) ?? 'General',
    tags: (str(meta.tags) ?? '').split(',').map((t) => t.trim()).filter(Boolean),
    source: SKILL_SOURCES.includes(source) ? source : 'vitra',
    addedAt: date(meta.added),
    updatedAt: date(meta.updated),
    license: str(front.license),
    compatibility,
    instructions: body,
    readme: readText(join(dir, 'README.md')),
    listing: readListing(dir, problems),
    files,
    dir,
  };
  return { skill, problems };
}

/**
 * Every top-level folder with a SKILL.md. Dot- and underscore-folders are
 * tooling (`_lib` holds the shared helpers), and the repo's own scripts,
 * dependencies and build output are not skills either.
 */
export function loadSkills(root) {
  const results = [];
  for (const entry of readdirSync(root, { withFileTypes: true })) {
    if (!entry.isDirectory() || /^[._]/.test(entry.name)) continue;
    if (!existsSync(join(root, entry.name, 'SKILL.md'))) continue;
    results.push({ folder: entry.name, ...readSkill(join(root, entry.name), entry.name) });
  }
  return results.sort((a, b) => (a.folder < b.folder ? -1 : 1));
}

/** The summary the library grid shows: no paths, no long text. */
export function toSummary(skill) {
  return {
    name: skill.name,
    displayName: skill.displayName,
    description: skill.description,
    author: skill.author,
    version: skill.version,
    category: skill.category,
    tags: skill.tags,
    source: skill.source,
    addedAt: skill.addedAt,
    fileCount: skill.files.length,
    size: skill.files.reduce((n, f) => n + f.size, 0),
  };
}

/** One skill's page, the same shape the webapp's SkillDetail type expects. */
export function toDetail(skill) {
  return {
    ...toSummary(skill),
    compatibility: skill.compatibility,
    updatedAt: skill.updatedAt,
    license: skill.license,
    instructions: skill.instructions,
    readme: skill.readme,
    about: skill.listing?.about ?? null,
    whenToUse: skill.listing?.whenToUse ?? null,
    features: skill.listing?.features ?? [],
    useCases: skill.listing?.useCases ?? [],
    mcpTools: skill.listing?.mcpTools ?? [],
    files: skill.files.map(({ path, size }) => ({ path, size })),
  };
}
