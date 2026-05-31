/** Load bundled prompt files and fill dynamic placeholders. */

import fs from 'node:fs';
import path from 'node:path';

import { PROMPTS_DIR } from './paths.js';

export function loadSystemPrompt(): string {
  return fs.readFileSync(path.join(PROMPTS_DIR, 'SYSTEM.md'), 'utf-8').trim();
}

export function loadPlanPrompt(): string {
  return fs.readFileSync(path.join(PROMPTS_DIR, 'PLAN.md'), 'utf-8').trim();
}

function formatLocalTime(date = new Date()): string {
  const pad = (n: number) => String(n).padStart(2, '0');
  return (
    `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())} ` +
    `${pad(date.getHours())}:${pad(date.getMinutes())}:${pad(date.getSeconds())}`
  );
}

/** Replace {{CWD}} and {{LOCAL_TIME}} placeholders. */
export function fillPlaceholders(prompt: string): string {
  return prompt
    .replaceAll('{{CWD}}', process.cwd())
    .replaceAll('{{LOCAL_TIME}}', formatLocalTime());
}
