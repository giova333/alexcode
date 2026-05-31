/** Write tool: create or overwrite files. */

import fs from 'node:fs';
import path from 'node:path';

import { expandUser } from '../../util/fsutil.js';
import type { Tool } from '../base.js';

export class WriteTool implements Tool {
  get name(): string {
    return 'write';
  }

  get description(): string {
    return 'Write content to a file, creating parent directories as needed.';
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        file_path: {
          type: 'string',
          description: 'Path to the file to write.',
        },
        content: {
          type: 'string',
          description: 'The content to write.',
        },
      },
      required: ['file_path', 'content'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const filePath: string = params.file_path;
    const content: string = params.content ?? '';
    const resolved = expandUser(filePath);

    try {
      fs.mkdirSync(path.dirname(resolved), { recursive: true });
      fs.writeFileSync(resolved, content);
      return `Wrote ${content.length} bytes to ${filePath}`;
    } catch (e: any) {
      if (e?.code === 'EACCES') return `Permission denied: ${filePath}`;
      return `Error writing ${filePath}: ${e?.message ?? e}`;
    }
  }
}
