/** Test fixtures: fake LLM provider, fake CLI, and agent wiring. */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';

import type { CLI } from '../src/cli/types.js';
import { buildConfig, type Config } from '../src/config/schema.js';
import { AgentLoop } from '../src/core/loop.js';
import type { HistoryStorage } from '../src/history/storage.js';
import {
  responseComplete,
  textDelta,
  thinkingDelta,
  toolUseEvent,
  type LLMProvider,
  type StreamEvent,
  type StreamParams,
} from '../src/llm/base.js';
import type { MemoryManager } from '../src/memory/manager.js';
import type { SkillLoader } from '../src/skills/loader.js';
import type { Skill } from '../src/skills/skill.js';
import type { Tool } from '../src/tools/base.js';
import { ToolExecutor } from '../src/tools/executor.js';
import { ToolRegistry } from '../src/tools/registry.js';
import type { ThinkingBlock } from '../src/core/message.js';

const ERROR_SENTINEL = Symbol('error');
interface ErrorSentinel {
  [ERROR_SENTINEL]: true;
  error: Error;
}
function isErrorSentinel(x: unknown): x is ErrorSentinel {
  return typeof x === 'object' && x !== null && ERROR_SENTINEL in x;
}

export class FakeLLMProvider implements LLMProvider {
  model = 'test-model';
  responses: Array<Array<StreamEvent | ErrorSentinel>> = [];
  calls: Array<{ system: string; messages: unknown; tools: unknown; maxTokens: number }> = [];

  setTextResponse(text: string, inputTokens = 100, outputTokens = 50): void {
    this.responses.push([
      textDelta(text),
      responseComplete({ input_tokens: inputTokens, output_tokens: outputTokens }, 'end_turn'),
    ]);
  }

  setToolThenText(
    toolName: string,
    toolInput: Record<string, any>,
    toolId = 'tool_001',
    finalText = 'Done.',
    inputTokens = 100,
    outputTokens = 50,
  ): void {
    this.responses.push([
      toolUseEvent(toolId, toolName, toolInput),
      responseComplete({ input_tokens: inputTokens, output_tokens: outputTokens }, 'tool_use'),
    ]);
    this.responses.push([
      textDelta(finalText),
      responseComplete({ input_tokens: inputTokens, output_tokens: outputTokens }, 'end_turn'),
    ]);
  }

  setMultiToolResponse(
    tools: Array<[string, string, Record<string, any>]>,
    finalText = 'Done.',
    inputTokens = 100,
    outputTokens = 50,
  ): void {
    const events: Array<StreamEvent | ErrorSentinel> = tools.map(([tid, name, inp]) =>
      toolUseEvent(tid, name, inp),
    );
    events.push(
      responseComplete({ input_tokens: inputTokens, output_tokens: outputTokens }, 'tool_use'),
    );
    this.responses.push(events);
    this.setTextResponse(finalText, inputTokens, outputTokens);
  }

  setThinkingThenText(
    thinking: string,
    text: string,
    thinkingBlocks?: ThinkingBlock[],
    inputTokens = 100,
    outputTokens = 50,
  ): void {
    this.responses.push([
      thinkingDelta(thinking),
      textDelta(text),
      responseComplete(
        { input_tokens: inputTokens, output_tokens: outputTokens },
        'end_turn',
        thinkingBlocks ?? [{ type: 'thinking', thinking, signature: 'sig_test' }],
      ),
    ]);
  }

  setErrorResponse(error: Error): void {
    this.responses.push([{ [ERROR_SENTINEL]: true, error }]);
  }

  async *stream(params: StreamParams): AsyncIterable<StreamEvent> {
    this.calls.push({
      system: params.system,
      messages: params.messages,
      tools: params.tools ?? null,
      maxTokens: params.maxTokens ?? 8192,
    });
    if (this.responses.length === 0) {
      yield textDelta('(no response configured)');
      yield responseComplete({ input_tokens: 10, output_tokens: 5 }, 'end_turn');
      return;
    }
    const events = this.responses.shift()!;
    for (const event of events) {
      if (isErrorSentinel(event)) throw event.error;
      yield event;
    }
  }
}

export class FakeCLI implements CLI {
  output: string[] = [];
  toolUses: Array<[string, Record<string, any>]> = [];
  toolResults: Array<[string, string, boolean]> = [];
  thinkingStarted = 0;
  thinkingEnded = 0;
  inputs: string[] = [];

  printWelcome(provider: string, model: string): void {
    this.output.push(`Welcome: ${provider}/${model}`);
  }
  printInfo(text: string): void {
    this.output.push(text);
  }
  printError(text: string): void {
    this.output.push(`ERROR: ${text}`);
  }
  printQuestion(text: string): void {
    this.output.push(`? ${text}`);
  }
  printTextDelta(text: string): void {
    this.output.push(text);
  }
  printThinkingDelta(text: string): void {
    this.output.push(`[thinking] ${text}`);
  }
  printAssistantText(text: string): void {
    this.output.push(text);
  }
  printToolUse(name: string, input: Record<string, any>): void {
    this.toolUses.push([name, input]);
  }
  printToolResult(name: string, result: string, isError: boolean): void {
    this.toolResults.push([name, result, isError]);
  }
  printUsage(inputTokens: number, outputTokens: number): void {
    this.output.push(`Tokens: ${inputTokens}in/${outputTokens}out`);
  }
  printCompactionNotice(): void {
    this.output.push('[compaction]');
  }
  startResponse(): void {}
  endResponse(): void {}
  startThinking(): void {
    this.thinkingStarted += 1;
  }
  endThinking(): void {
    this.thinkingEnded += 1;
  }
  async getInput(): Promise<string | null> {
    return this.inputs.length > 0 ? this.inputs.shift()! : null;
  }
  setSkills(): void {}
}

export function makeTestConfig(overrides: Record<string, any> = {}): Config {
  return buildConfig({
    provider: 'anthropic',
    model: 'test-model',
    max_tokens: 1024,
    anthropic: { api_key: 'test-key' },
    reasoning: { enabled: false },
    compaction: { threshold_tokens: 500, keep_recent_messages: 4 },
    memory: { enabled: true, memory_file: '.agent/memory/MEMORY.md', scope: 'project' },
    mem0: { enabled: false },
    history: { dir: '.agent/history/' },
    skills: { dirs: [] },
    tools: { bash_timeout: 10 },
    ...overrides,
  });
}

export interface BuildAgentOptions {
  extraTools?: Tool[];
  memoryManager?: MemoryManager | null;
  history?: HistoryStorage | null;
  skillLoader?: SkillLoader | null;
  skills?: Skill[] | null;
}

export function buildAgent(
  fakeLlm: FakeLLMProvider,
  fakeCli: FakeCLI,
  config: Config,
  projectDir: string,
  opts: BuildAgentOptions = {},
): AgentLoop {
  const registry = new ToolRegistry();
  for (const t of opts.extraTools ?? []) registry.register(t);
  const executor = new ToolExecutor(registry);
  return new AgentLoop({
    config,
    llm: fakeLlm,
    cli: fakeCli,
    projectDir,
    toolRegistry: registry,
    toolExecutor: executor,
    memoryManager: opts.memoryManager ?? null,
    history: opts.history ?? null,
    skillLoader: opts.skillLoader ?? null,
    skills: opts.skills ?? null,
  });
}

/** Create a unique temp directory for a test. */
export function tmpDir(prefix = 'alexcode-test-'): string {
  return fs.mkdtempSync(path.join(os.tmpdir(), prefix));
}
