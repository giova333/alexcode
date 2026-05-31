/**
 * Live eval harness. Drives the REAL alexcode CLI end-to-end: it spawns the
 * built binary (`node dist/index.js -p "<prompt>"`) in a throwaway workspace,
 * so the eval exercises the true entrypoint — index.ts → bootstrap.ts → CLI →
 * AgentLoop → tools — exactly as a user would. Grades by inspecting the
 * workspace and the CLI's stdout.
 */

import { spawn } from 'node:child_process';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { fileURLToPath } from 'node:url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = path.dirname(HERE);
const CLI_ENTRY = path.resolve(REPO_ROOT, 'dist/index.js');

const DEFAULT_MODEL = 'claude-haiku-4-5-20251001';
const DEFAULT_TIMEOUT_MS = 120_000;
const VERBOSE = process.env.EVAL_VERBOSE === '1';

export interface GradeContext {
  workspace: string;
  /** Everything the CLI wrote to stdout (ANSI stripped). */
  finalText: string;
  /** Tool names parsed from the CLI's "⚡ <tool>" markers, in order. */
  toolCalls: string[];
  /** The CLI's stderr (diagnostics), for debugging a failure. */
  stderr: string;
}

export interface GradeResult {
  pass: boolean;
  detail: string;
}

export interface EvalScenario {
  name: string;
  description: string;
  setup?: (workspace: string) => void | Promise<void>;
  prompt: string | ((workspace: string) => string);
  grade: (ctx: GradeContext) => GradeResult | Promise<GradeResult>;
}

export interface EvalOutcome extends GradeResult {
  name: string;
  durationMs: number;
  error?: string;
}

// eslint-disable-next-line no-control-regex -- intentionally matching the ESC control char
const ANSI = /\x1b\[[0-9;]*m/g;
const stripAnsi = (s: string): string => s.replace(ANSI, '');

/**
 * A project config that disables stateful/networked subsystems (mem0, memory,
 * skills) so evals are reproducible and cheap. The model is overridable via
 * EVAL_MODEL; the API key flows from the inherited ANTHROPIC_API_KEY env (the
 * bundled config.default.yaml interpolates ${ANTHROPIC_API_KEY}).
 */
function writeWorkspaceConfig(workspace: string, model: string): void {
  const yaml = [
    `model: ${model}`,
    'reasoning:',
    '  enabled: false',
    'memory:',
    '  enabled: false',
    'mem0:',
    '  enabled: false',
    'skills:',
    '  dirs: []',
    '',
  ].join('\n');
  fs.writeFileSync(path.join(workspace, 'config.yaml'), yaml);
}

interface CliRun {
  stdout: string;
  stderr: string;
  code: number | null;
  timedOut: boolean;
}

function runCli(prompt: string, workspace: string, timeoutMs: number): Promise<CliRun> {
  return new Promise((resolve) => {
    const child = spawn(process.execPath, [CLI_ENTRY, '-p', prompt], {
      cwd: workspace,
      env: process.env,
    });
    let stdout = '';
    let stderr = '';
    let timedOut = false;
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill('SIGKILL');
    }, timeoutMs);

    child.stdout.on('data', (d: Buffer) => {
      stdout += d.toString();
      if (VERBOSE) process.stdout.write(d);
    });
    child.stderr.on('data', (d: Buffer) => {
      stderr += d.toString();
      if (VERBOSE) process.stderr.write(d);
    });
    child.on('error', (err) => {
      clearTimeout(timer);
      resolve({ stdout, stderr: String(err), code: 1, timedOut });
    });
    child.on('close', (code) => {
      clearTimeout(timer);
      resolve({ stdout, stderr, code, timedOut });
    });
  });
}

export async function runScenario(scenario: EvalScenario): Promise<EvalOutcome> {
  const start = Date.now();

  if (!fs.existsSync(CLI_ENTRY)) {
    return {
      name: scenario.name,
      durationMs: 0,
      pass: false,
      detail: `built CLI not found at ${CLI_ENTRY} — run \`npm run build\` first`,
      error: 'missing build',
    };
  }

  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'alexcode-eval-'));
  try {
    await scenario.setup?.(workspace);
    writeWorkspaceConfig(workspace, process.env.EVAL_MODEL ?? DEFAULT_MODEL);

    const prompt =
      typeof scenario.prompt === 'function' ? scenario.prompt(workspace) : scenario.prompt;
    const timeoutMs = Number(process.env.EVAL_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);

    const run = await runCli(prompt, workspace, timeoutMs);
    if (run.timedOut) {
      return {
        name: scenario.name,
        durationMs: Date.now() - start,
        pass: false,
        detail: `CLI timed out after ${timeoutMs}ms`,
      };
    }

    const finalText = stripAnsi(run.stdout);
    const toolCalls = [...finalText.matchAll(/⚡\s+(\S+)/g)].map((m) => m[1]!);

    const grade = await scenario.grade({
      workspace,
      finalText,
      toolCalls,
      stderr: stripAnsi(run.stderr),
    });
    return { name: scenario.name, durationMs: Date.now() - start, ...grade };
  } catch (e: any) {
    return {
      name: scenario.name,
      durationMs: Date.now() - start,
      pass: false,
      detail: 'threw before grading',
      error: e?.message ?? String(e),
    };
  } finally {
    fs.rmSync(workspace, { recursive: true, force: true });
  }
}
