/** Edit tool: targeted string replacement in files. */

import fs from 'node:fs';

import { expandUser } from '../../util/fsutil.js';
import type { Tool } from '../base.js';

function countOccurrences(haystack: string, needle: string): number {
  if (needle === '') return 0;
  let count = 0;
  let idx = haystack.indexOf(needle);
  while (idx !== -1) {
    count++;
    idx = haystack.indexOf(needle, idx + needle.length);
  }
  return count;
}

export class EditTool implements Tool {
  get name(): string {
    return 'edit';
  }

  get description(): string {
    return (
      'Edit a file by replacing an exact string match. ' +
      'The old_string must appear exactly once in the file (unless replace_all is true).'
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        file_path: { type: 'string', description: 'Path to the file to edit.' },
        old_string: { type: 'string', description: 'The exact text to find and replace.' },
        new_string: { type: 'string', description: 'The replacement text.' },
        replace_all: {
          type: 'boolean',
          description: 'Replace all occurrences (default: false).',
        },
      },
      required: ['file_path', 'old_string', 'new_string'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const filePath: string = params.file_path;
    const oldString: string = params.old_string;
    const newString: string = params.new_string;
    const replaceAll: boolean = params.replace_all ?? false;
    const resolved = expandUser(filePath);

    if (!fs.existsSync(resolved)) {
      return `File not found: ${filePath}`;
    }

    let content: string;
    try {
      content = fs.readFileSync(resolved, 'utf-8');
    } catch (e: any) {
      if (e?.code === 'EACCES') return `Permission denied: ${filePath}`;
      throw e;
    }

    const count = countOccurrences(content, oldString);
    if (count === 0) {
      return `old_string not found in ${filePath}`;
    }
    if (count > 1 && !replaceAll) {
      return (
        `old_string found ${count} times in ${filePath}. ` +
        'Provide more context to make it unique, or set replace_all=true.'
      );
    }

    let newContent: string;
    if (replaceAll) {
      newContent = content.split(oldString).join(newString);
    } else {
      const idx = content.indexOf(oldString);
      newContent = content.slice(0, idx) + newString + content.slice(idx + oldString.length);
    }

    fs.writeFileSync(resolved, newContent);
    const replacements = replaceAll ? count : 1;
    return `Replaced ${replacements} occurrence(s) in ${filePath}`;
  }
}
