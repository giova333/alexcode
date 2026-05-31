/** Bash tool: execute shell commands. */

import { spawn } from 'node:child_process';

import type { Tool } from '../base.js';

export class BashTool implements Tool {
  constructor(private timeout = 120) {}

  get name(): string {
    return 'bash';
  }

  get description(): string {
    return 'Execute a shell command and return its output.';
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        command: {
          type: 'string',
          description: 'The shell command to execute.',
        },
        timeout: {
          type: 'integer',
          description: `Timeout in seconds (default: ${this.timeout}).`,
        },
      },
      required: ['command'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const command: string = params.command;
    const effectiveTimeout: number =
      typeof params.timeout === 'number' ? params.timeout : this.timeout;

    return new Promise<string>((resolve) => {
      const proc = spawn(command, { shell: true });
      const stdoutChunks: Buffer[] = [];
      const stderrChunks: Buffer[] = [];
      let timedOut = false;

      const timer = setTimeout(() => {
        timedOut = true;
        proc.kill('SIGKILL');
      }, effectiveTimeout * 1000);

      proc.stdout.on('data', (d: Buffer) => stdoutChunks.push(d));
      proc.stderr.on('data', (d: Buffer) => stderrChunks.push(d));

      proc.on('error', (err) => {
        clearTimeout(timer);
        resolve(`Error executing command: ${err.message}`);
      });

      proc.on('close', (code) => {
        clearTimeout(timer);
        if (timedOut) {
          resolve(`Command timed out after ${effectiveTimeout}s`);
          return;
        }
        const stdout = Buffer.concat(stdoutChunks).toString('utf-8');
        const stderr = Buffer.concat(stderrChunks).toString('utf-8');
        const parts: string[] = [];
        if (stdout) parts.push(stdout);
        if (stderr) parts.push(`STDERR:\n${stderr}`);
        if (code !== 0 && code !== null) parts.push(`Exit code: ${code}`);
        resolve(parts.join('\n') || '(no output)');
      });
    });
  }
}
