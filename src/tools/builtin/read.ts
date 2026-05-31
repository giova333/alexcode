/** Read tool: read file contents with line numbers. */

import fs from 'node:fs';

import { expandUser } from '../../util/fsutil.js';
import type { Tool } from '../base.js';

export class ReadTool implements Tool {
  get name(): string {
    return 'read';
  }

  get description(): string {
    return 'Read a file and return its contents with line numbers.';
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        file_path: {
          type: 'string',
          description: 'Absolute or relative path to the file.',
        },
        offset: {
          type: 'integer',
          description: 'Line number to start reading from (1-based).',
        },
        limit: {
          type: 'integer',
          description: 'Maximum number of lines to read.',
        },
      },
      required: ['file_path'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const filePath: string = params.file_path;
    const offset: number = typeof params.offset === 'number' ? params.offset : 1;
    const limit: number = typeof params.limit === 'number' ? params.limit : 2000;

    const resolved = expandUser(filePath);
    let stat: fs.Stats;
    try {
      stat = fs.statSync(resolved);
    } catch {
      return `File not found: ${filePath}`;
    }
    if (!stat.isFile()) {
      return `Not a file: ${filePath}`;
    }

    let text: string;
    try {
      text = fs.readFileSync(resolved, 'utf-8');
    } catch (e: any) {
      if (e?.code === 'EACCES') return `Permission denied: ${filePath}`;
      throw e;
    }

    // Mirror Python str.splitlines(): drop a single trailing newline.
    const lines = text.split('\n');
    if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();

    const start = Math.max(0, offset - 1);
    const end = start + limit;
    const selected = lines.slice(start, end);

    const numbered: string[] = [];
    for (let i = 0; i < selected.length; i++) {
      let line = selected[i] ?? '';
      if (line.length > 2000) line = line.slice(0, 2000) + '...';
      const lineNo = start + i + 1;
      numbered.push(`${String(lineNo).padStart(6)}\t${line}`);
    }

    return numbered.join('\n') || '(empty file)';
  }
}
