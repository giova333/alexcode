/**
 * Live eval harness: drives the real AgentLoop against the Anthropic API on a
 * throwaway workspace and grades the outcome. Reuses the production modules so
 * the evals exercise the same code paths the CLI does.
 */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import type { CLI } from '../src/cli/types.js';
import { buildConfig } from '../src/config/schema.js';
import { AgentLoop } from '../src/core/loop.js';
import { AnthropicProvider } from '../src/llm/anthropic.js';
import { registerBuiltins } from '../src/tools/builtin/index.js';
import { ToolExecutor } from '../src/tools/executor.js';
import { ToolRegistry } from '../src/tools/registry.js';

const DEFAULT_MODEL = 'claude-haiku-4-5-20251001';
const DEFAULT_TIMEOUT_MS = 120_000;
const VERBOSE = process.env.EVAL_VERBOSE === '1';

export interface GradeContext {
  workspace: string;
  /** Concatenated text of all assistant messages produced during the turn. */
  finalText: string;
  /** Names of every tool the agent invoked, in order. */
  toolCalls: string[];
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

/** Minimal CLI that never blocks and records what the agent did. */
class HeadlessCLI implements CLI {
  assistantText = '';
  toolCalls: string[] = [];

  printWelcome(): void {}
  printInfo(message: string): void {
    if (VERBOSE) process.stdout.write(`  · ${message}\n`);
  }
  printError(message: string): void {
    if (VERBOSE) process.stdout.write(`  ! ${message}\n`);
  }
  printQuestion(question: string): void {
    if (VERBOSE) process.stdout.write(`  ? ${question}\n`);
  }
  printTextDelta(text: string): void {
    this.assistantText += text;
    if (VERBOSE) process.stdout.write(text);
  }
  printThinkingDelta(text: string): void {
    if (VERBOSE) process.stdout.write(text);
  }
  printAssistantText(text: string): void {
    this.assistantText += text;
  }
  printToolUse(name: string): void {
    this.toolCalls.push(name);
    if (VERBOSE) process.stdout.write(`\n  ⚡ ${name}\n`);
  }
  printToolResult(): void {}
  printUsage(): void {}
  printCompactionNotice(): void {}
  startResponse(): void {}
  endResponse(): void {}
  startThinking(): void {}
  endThinking(): void {}
  // Non-interactive: ask_user resolves to "no answer" instead of blocking.
  async getInput(): Promise<string | null> {
    return null;
  }
  setSkills(): void {}
}

function withTimeout<T>(promise: Promise<T>, ms: number, label: string): Promise<T> {
  return new Promise<T>((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error(`${label} timed out after ${ms}ms`)), ms);
    promise.then(
      (v) => {
        clearTimeout(timer);
        resolve(v);
      },
      (e) => {
        clearTimeout(timer);
        reject(e);
      },
    );
  });
}

export async function runScenario(scenario: EvalScenario): Promise<EvalOutcome> {
  const start = Date.now();
  const workspace = fs.mkdtempSync(path.join(os.tmpdir(), 'alexcode-eval-'));
  const originalCwd = process.cwd();

  try {
    await scenario.setup?.(workspace);

    const model = process.env.EVAL_MODEL ?? DEFAULT_MODEL;
    const config = buildConfig({
      model,
      anthropic: { api_key: process.env.ANTHROPIC_API_KEY ?? '' },
      reasoning: { enabled: false },
      memory: { enabled: false },
      mem0: { enabled: false },
      skills: { dirs: [] },
    });

    const cli = new HeadlessCLI();
    const llm = new AnthropicProvider(config.anthropic, config.model);
    const registry = new ToolRegistry();
    registerBuiltins(registry, config, cli, null);
    const executor = new ToolExecutor(registry);

    const loop = new AgentLoop({
      config,
      llm,
      cli,
      projectDir: workspace,
      toolRegistry: registry,
      toolExecutor: executor,
      memoryManager: null,
      history: null,
    });

    const prompt =
      typeof scenario.prompt === 'function' ? scenario.prompt(workspace) : scenario.prompt;

    // File tools resolve relative paths against process.cwd(); run inside the
    // scratch workspace so the agent's edits land there.
    process.chdir(workspace);
    const timeoutMs = Number(process.env.EVAL_TIMEOUT_MS ?? DEFAULT_TIMEOUT_MS);
    try {
      await withTimeout(loop.processMessage(prompt), timeoutMs, scenario.name);
    } finally {
      process.chdir(originalCwd);
    }

    const finalText = loop.conversationState.messages
      .filter((m) => m.role === 'assistant')
      .map((m) => m.text)
      .filter((t) => t.length > 0)
      .join('\n');

    const grade = await scenario.grade({ workspace, finalText, toolCalls: cli.toolCalls });
    return { name: scenario.name, durationMs: Date.now() - start, ...grade };
  } catch (e: any) {
    process.chdir(originalCwd);
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
