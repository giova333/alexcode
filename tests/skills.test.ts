import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { extractFrontmatter, SkillLoader } from '../src/skills/loader.js';
import { extractBody, Skill } from '../src/skills/skill.js';
import { tmpDir } from './fakes.js';

const dirs: string[] = [];
function newDir(): string {
  const d = tmpDir();
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

const SKILL_MD = `---
name: review
description: Review a PR. Use when asked to review.
user-invocable: true
argument-hint: "[pr-number]"
allowed-tools: read, grep
---

# Review skill
Review PR $ARGUMENTS now. First arg is $0.`;

function writeSkill(base: string, dirName: string, content: string): void {
  const dir = path.join(base, 'skills', dirName);
  fs.mkdirSync(dir, { recursive: true });
  fs.writeFileSync(path.join(dir, 'SKILL.md'), content);
}

describe('frontmatter / body extraction', () => {
  it('extracts frontmatter and body', () => {
    const fm = extractFrontmatter(SKILL_MD);
    expect(fm).toContain('name: review');
    const body = extractBody(SKILL_MD);
    expect(body.startsWith('# Review skill')).toBe(true);
  });

  it('returns null frontmatter when absent', () => {
    expect(extractFrontmatter('no frontmatter here')).toBeNull();
  });
});

describe('SkillLoader', () => {
  it('discovers skills and parses metadata', () => {
    const d = newDir();
    writeSkill(d, 'review', SKILL_MD);
    const loader = new SkillLoader(['skills/'], d);
    const skills = loader.loadAll();
    expect(skills).toHaveLength(1);
    const s = skills[0]!;
    expect(s.name).toBe('review');
    expect(s.userInvocable).toBe(true);
    expect(s.argumentHint).toBe('[pr-number]');
    expect(s.allowedTools).toEqual(['read', 'grep']);
  });

  it('filters invocable and model-available skills', () => {
    const d = newDir();
    writeSkill(d, 'review', SKILL_MD);
    writeSkill(
      d,
      'bg',
      '---\nname: bg\ndescription: background\nuser-invocable: false\ndisable-model-invocation: true\n---\nbody',
    );
    const loader = new SkillLoader(['skills/'], d);
    const skills = loader.loadAll();
    expect(loader.getInvocable(skills).map((s) => s.name)).toEqual(['review']);
    expect(loader.getModelAvailable(skills).map((s) => s.name)).toEqual(['review']);
    expect(loader.getByName('bg', skills)!.name).toBe('bg');
  });
});

describe('Skill.render', () => {
  it('substitutes arguments', () => {
    const d = newDir();
    writeSkill(d, 'review', SKILL_MD);
    const loader = new SkillLoader(['skills/'], d);
    const skill = loader.getByName('review', loader.loadAll())!;
    const rendered = skill.render('123 main');
    expect(rendered).toContain('Review PR 123 main now');
    expect(rendered).toContain('First arg is 123.');
  });

  it('resolves dynamic !`command` context', () => {
    const skill = new Skill({ name: 'x', skillDir: null });
    // Bypass loadBody by stubbing body via render of inline content is not possible;
    // instead verify the regex path on a crafted skill dir.
    const d = newDir();
    const dir = path.join(d, 'skills', 'dyn');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'SKILL.md'), '---\nname: dyn\n---\nout: !`echo hi`');
    const loaded = new SkillLoader(['skills/'], d).getByName(
      'dyn',
      new SkillLoader(['skills/'], d).loadAll(),
    )!;
    expect(loaded.render()).toContain('out: hi');
    expect(skill.render()).toBe('');
  });
});
