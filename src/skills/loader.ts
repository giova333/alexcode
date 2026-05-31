/** Discover and load skills from SKILL.md files following Anthropic convention. */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { parse as parseYaml } from 'yaml';

import { Skill } from './skill.js';

export class SkillLoader {
  private dirs: string[] = [];

  constructor(skillDirs: string[], baseDir: string) {
    for (const d of skillDirs) {
      this.dirs.push(path.join(baseDir, d));
    }
    this.dirs.push(path.join(baseDir, '.agent', 'skills'));
    this.dirs.push(path.join(os.homedir(), '.config', 'agent', 'skills'));
  }

  /** Discover all skills. Only reads frontmatter (metadata), not body. */
  loadAll(): Skill[] {
    const seenNames = new Set<string>();
    const skills: Skill[] = [];

    for (const skillDir of this.dirs) {
      if (!fs.existsSync(skillDir)) continue;
      let entries: string[];
      try {
        entries = fs.readdirSync(skillDir).sort();
      } catch {
        continue;
      }
      for (const entry of entries) {
        const entryPath = path.join(skillDir, entry);
        let stat: fs.Stats;
        try {
          stat = fs.statSync(entryPath);
        } catch {
          continue;
        }
        if (!stat.isDirectory()) continue;
        const skillFile = path.join(entryPath, 'SKILL.md');
        if (!fs.existsSync(skillFile)) continue;

        const skill = this.loadMetadata(skillFile, entryPath);
        if (skill && !seenNames.has(skill.name)) {
          seenNames.add(skill.name);
          skills.push(skill);
        }
      }
    }
    return skills;
  }

  private loadMetadata(skillFile: string, skillDir: string): Skill | null {
    let content: string;
    try {
      content = fs.readFileSync(skillFile, 'utf-8');
    } catch {
      return null;
    }

    const frontmatter = extractFrontmatter(content);
    const dirName = path.basename(skillDir);
    if (frontmatter === null) {
      return new Skill({ name: dirName, skillDir });
    }

    let data: any;
    try {
      data = parseYaml(frontmatter);
    } catch {
      return null;
    }

    if (!data || typeof data !== 'object') {
      return new Skill({ name: dirName, skillDir });
    }

    const allowedRaw = data['allowed-tools'] ?? '';
    let allowedTools: string[];
    if (typeof allowedRaw === 'string') {
      allowedTools = allowedRaw
        .split(',')
        .map((t: string) => t.trim())
        .filter((t: string) => t.length > 0);
    } else if (Array.isArray(allowedRaw)) {
      allowedTools = allowedRaw;
    } else {
      allowedTools = [];
    }

    return new Skill({
      name: data.name ?? dirName,
      description: data.description ?? '',
      userInvocable: data['user-invocable'] ?? true,
      disableModelInvocation: data['disable-model-invocation'] ?? false,
      argumentHint: data['argument-hint'] ?? '',
      allowedTools,
      skillDir,
    });
  }

  getByName(name: string, skills: Skill[]): Skill | null {
    return skills.find((s) => s.name === name) ?? null;
  }

  getInvocable(skills: Skill[]): Skill[] {
    return skills.filter((s) => s.userInvocable);
  }

  getModelAvailable(skills: Skill[]): Skill[] {
    return skills.filter((s) => !s.disableModelInvocation);
  }
}

export function extractFrontmatter(content: string): string | null {
  if (!content.startsWith('---')) return null;
  const end = content.indexOf('---', 3);
  if (end === -1) return null;
  return content.slice(3, end).trim();
}
