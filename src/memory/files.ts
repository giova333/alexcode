/** MEMORY.md file I/O — long-term, non-temporal knowledge. */

import fs from 'node:fs';
import path from 'node:path';

import { expandUser } from '../util/fsutil.js';

/**
 * Reads and writes the main MEMORY.md file (stable, long-term knowledge).
 *
 * Absolute paths and `~`-prefixed paths are used as-is (a user-scope file shared
 * across projects). Relative paths are resolved under `baseDir`.
 */
export class MemoryFiles {
  private memoryFile: string;

  constructor(memoryFile: string, baseDir: string) {
    const expanded = expandUser(memoryFile);
    this.memoryFile = path.isAbsolute(expanded) ? expanded : path.join(baseDir, expanded);
  }

  read(): string {
    if (fs.existsSync(this.memoryFile)) {
      return fs.readFileSync(this.memoryFile, 'utf-8');
    }
    return '';
  }

  write(content: string): void {
    fs.mkdirSync(path.dirname(this.memoryFile), { recursive: true });
    fs.writeFileSync(this.memoryFile, content);
  }

  append(content: string): void {
    fs.mkdirSync(path.dirname(this.memoryFile), { recursive: true });
    const existing = this.read();
    let separator: string;
    if (existing && !existing.endsWith('\n\n')) {
      separator = '\n\n';
    } else if (existing) {
      separator = '\n';
    } else {
      separator = '';
    }
    fs.writeFileSync(this.memoryFile, existing + separator + content);
  }
}
