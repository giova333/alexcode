/** Grep tool: search file contents using ripgrep or grep. */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import path from 'node:path';

import type { Tool } from '../base.js';

function which(cmd: string): boolean {
  const dirs = (process.env.PATH ?? '').split(path.delimiter);
  for (const dir of dirs) {
    if (!dir) continue;
    try {
      fs.accessSync(path.join(dir, cmd), fs.constants.X_OK);
      return true;
    } catch {
      /* not here */
    }
  }
  return false;
}

interface ProcResult {
  stdout: string;
  stderr: string;
  code: number | null;
  timedOut: boolean;
}

function runCommand(cmd: string, args: string[], timeoutMs: number): Promise<ProcResult> {
  return new Promise((resolve) => {
    const proc = spawn(cmd, args);
    const stdoutChunks: Buffer[] = [];
    const stderrChunks: Buffer[] = [];
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      proc.kill('SIGKILL');
    }, timeoutMs);

    proc.stdout.on('data', (d: Buffer) => stdoutChunks.push(d));
    proc.stderr.on('data', (d: Buffer) => stderrChunks.push(d));
    proc.on('error', () => {
      clearTimeout(timer);
      resolve({ stdout: '', stderr: 'spawn error', code: 2, timedOut });
    });
    proc.on('close', (code) => {
      clearTimeout(timer);
      resolve({
        stdout: Buffer.concat(stdoutChunks).toString('utf-8'),
        stderr: Buffer.concat(stderrChunks).toString('utf-8'),
        code,
        timedOut,
      });
    });
  });
}

export class GrepTool implements Tool {
  get name(): string {
    return 'grep';
  }

  get description(): string {
    return 'Search file contents for a regex pattern. Uses ripgrep if available, falls back to grep.';
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        pattern: { type: 'string', description: 'Regex pattern to search for.' },
        path: {
          type: 'string',
          description: 'File or directory to search (default: current directory).',
        },
        glob: { type: 'string', description: "File glob filter (e.g. '*.py')." },
        case_insensitive: {
          type: 'boolean',
          description: 'Case insensitive search (default: false).',
        },
        max_results: {
          type: 'integer',
          description: 'Maximum number of matching lines to return (default: 50).',
        },
      },
      required: ['pattern'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const pattern: string = params.pattern;
    const searchPath: string = params.path ?? '.';
    const glob: string | undefined = params.glob;
    const caseInsensitive: boolean = params.case_insensitive ?? false;
    const maxResults: number = typeof params.max_results === 'number' ? params.max_results : 50;

    const useRg = which('rg');
    let cmd: string;
    let args: string[];
    if (useRg) {
      cmd = 'rg';
      args = ['--no-heading', '--line-number', `--max-count=${maxResults}`];
      if (caseInsensitive) args.push('-i');
      if (glob) args.push('--glob', glob);
      args.push(pattern, searchPath);
    } else {
      cmd = 'grep';
      args = ['-rn'];
      if (caseInsensitive) args.push('-i');
      args.push(pattern, searchPath);
    }

    const result = await runCommand(cmd, args, 30_000);
    if (result.timedOut) {
      return 'Search timed out after 30s';
    }

    const output = result.stdout;
    if (!output) {
      if (result.code === 1) return `No matches found for '${pattern}'`;
      if (result.stderr) return `Error: ${result.stderr}`;
      return `No matches found for '${pattern}'`;
    }

    let lines = output.split('\n');
    if (lines.length > 0 && lines[lines.length - 1] === '') lines.pop();
    if (lines.length > maxResults) {
      lines = lines.slice(0, maxResults);
      lines.push(`... (truncated to ${maxResults} results)`);
    }
    return lines.join('\n');
  }
}
