/**
 * Research workflows as Pi Skills (contracts/p10.md §九): one Markdown file per workflow in services/agent/skills/
 * (frontmatter name + description). Pi lists them in the system prompt with their file location; the model loads
 * one with the `read` tool, which here reads only these files (tools.ts `skills.read`).
 */
import { readFileSync } from 'node:fs';
import { basename } from 'node:path';
import { fileURLToPath } from 'node:url';
import { loadSkillsFromDir, stripFrontmatter, type LoadSkillsResult, type Skill } from '@earendil-works/pi-coding-agent';

/** src/ in development, dist/ in the image: the skills directory sits next to both. */
export const SKILLS_DIR = fileURLToPath(new URL('../skills/', import.meta.url));

let loaded: LoadSkillsResult | null = null;

/** Loaded once per process; the files ship with the image. */
export function researchSkills(): LoadSkillsResult {
  if (!loaded) {
    loaded = loadSkillsFromDir({ dir: SKILLS_DIR, source: 'research' });
    for (const item of loaded.diagnostics) console.warn(`skill ${item.path ?? ''}: ${item.message}`);
  }
  return loaded;
}

/** A skill by name, file name or full location ("/app/skills/synonym-comparison.md" → synonym-comparison). */
export function findSkill(ref: string): Skill | undefined {
  const key = basename(String(ref ?? '').trim().replace(/\\/g, '/')).replace(/\.md$/i, '');
  return researchSkills().skills.find(skill => skill.name === key || basename(skill.filePath, '.md') === key);
}

/** Body of a skill file without frontmatter; `title` is its first heading. */
export function readSkill(skill: Skill): { title: string; content: string } {
  const content = stripFrontmatter(readFileSync(skill.filePath, 'utf8')).trim();
  const title = /^#\s+(.+)$/m.exec(content)?.[1].trim() ?? skill.name;
  return { title, content };
}
