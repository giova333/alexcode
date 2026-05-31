/** Skill data model following Anthropic's Agent Skills convention. */

import { execSync } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

export interface SkillInit {
  name: string;
  description?: string;
  userInvocable?: boolean;
  disableModelInvocation?: boolean;
  argumentHint?: string;
  allowedTools?: string[];
  skillDir?: string | null;
}

export class Skill {
  name: string;
  description: string;
  userInvocable: boolean;
  disableModelInvocation: boolean;
  argumentHint: string;
  allowedTools: string[];
  skillDir: string | null;
  private body: string | null = null;

  constructor(init: SkillInit) {
    this.name = init.name;
    this.description = init.description ?? '';
    this.userInvocable = init.userInvocable ?? true;
    this.disableModelInvocation = init.disableModelInvocation ?? false;
    this.argumentHint = init.argumentHint ?? '';
    this.allowedTools = init.allowedTools ?? [];
    this.skillDir = init.skillDir ?? null;
  }

  /** Load the full SKILL.md body (instructions below frontmatter). Lazy. */
  loadBody(): string {
    if (this.body !== null) return this.body;
    if (this.skillDir === null) return '';
    const skillFile = path.join(this.skillDir, 'SKILL.md');
    if (!fs.existsSync(skillFile)) return '';
    const content = fs.readFileSync(skillFile, 'utf-8');
    this.body = extractBody(content);
    return this.body;
  }

  /**
   * Render the skill body with argument substitution.
   *
   *   $ARGUMENTS      - all arguments
   *   $ARGUMENTS[N]   - specific argument by index
   *   $0, $1, $2      - shorthand for $ARGUMENTS[N]
   *   !`command`      - dynamic context (shell command output)
   */
  render(args = ''): string {
    let body = this.loadBody();
    if (!body) return '';

    if (args) {
      const argsList = args.split(/\s+/).filter((s) => s.length > 0);
      if (body.includes('$ARGUMENTS')) {
        body = body.split('$ARGUMENTS').join(args);
        argsList.forEach((arg, i) => {
          body = body.split(`$ARGUMENTS[${i}]`).join(arg);
          body = body.split(`$${i}`).join(arg);
        });
      } else {
        body += `\nARGUMENTS: ${args}`;
      }
    }

    body = resolveDynamicContext(body);
    return body;
  }
}

export function extractBody(content: string): string {
  if (!content.startsWith('---')) return content;
  const end = content.indexOf('---', 3);
  if (end === -1) return content;
  let bodyStart = end + 3;
  if (bodyStart < content.length && content[bodyStart] === '\n') bodyStart += 1;
  return content.slice(bodyStart).trim();
}

function resolveDynamicContext(body: string): string {
  return body.replace(/!`([^`]+)`/g, (_match, cmd: string) => {
    try {
      const out = execSync(cmd, { shell: '/bin/sh', timeout: 10_000, encoding: 'utf-8' });
      return out.trim();
    } catch (e: any) {
      if (e?.signal === 'SIGTERM' || e?.code === 'ETIMEDOUT') {
        return `(command timed out: ${cmd})`;
      }
      return `(command failed: ${cmd})`;
    }
  });
}
