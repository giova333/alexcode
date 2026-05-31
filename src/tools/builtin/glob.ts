/** Glob tool: find files by pattern. */

import fs from 'node:fs';
import path from 'node:path';
import fastGlob from 'fast-glob';

import { expandUser } from '../../util/fsutil.js';
import type { Tool } from '../base.js';

export class GlobTool implements Tool {
  get name(): string {
    return 'glob';
  }

  get description(): string {
    return 'Find files matching a glob pattern. Returns file paths sorted by modification time.';
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        pattern: {
          type: 'string',
          description: "Glob pattern (e.g. '**/*.py', 'src/**/*.ts').",
        },
        path: {
          type: 'string',
          description: 'Directory to search in (default: current directory).',
        },
      },
      required: ['pattern'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const pattern: string = params.pattern;
    const searchPath: string = params.path ?? '.';
    const base = expandUser(searchPath);

    let stat: fs.Stats;
    try {
      stat = fs.statSync(base);
    } catch {
      return `Not a directory: ${searchPath}`;
    }
    if (!stat.isDirectory()) {
      return `Not a directory: ${searchPath}`;
    }

    let matches: string[];
    try {
      matches = await fastGlob(pattern, {
        cwd: base,
        onlyFiles: true,
        dot: true,
        absolute: true,
      });
    } catch (e: any) {
      return `Invalid glob pattern: ${e?.message ?? e}`;
    }

    if (matches.length === 0) {
      return `No files matching '${pattern}' in ${searchPath}`;
    }

    // Sort by mtime descending.
    const withMtime = matches.map((f) => {
      let mtime = 0;
      try {
        mtime = fs.statSync(f).mtimeMs;
      } catch {
        /* ignore */
      }
      return { f, mtime };
    });
    withMtime.sort((a, b) => b.mtime - a.mtime);

    const maxResults = 100;
    const lines = withMtime
      .slice(0, maxResults)
      .map((m) => normalizeOutputPath(m.f, base, searchPath));
    if (withMtime.length > maxResults) {
      lines.push(`... and ${withMtime.length - maxResults} more files`);
    }
    return lines.join('\n');
  }
}

// Python's base.glob() returns paths joined onto the base (e.g. "./foo.py" when
// base is "."). fast-glob with absolute:true returns absolute paths; re-derive a
// base-relative join to keep output shape close to the original.
function normalizeOutputPath(absolute: string, base: string, originalBase: string): string {
  const rel = path.relative(path.resolve(base), absolute);
  if (originalBase === '.') return rel;
  return path.join(originalBase, rel);
}
