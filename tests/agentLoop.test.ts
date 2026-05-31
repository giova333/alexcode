import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import type { Tool } from '../src/tools/base.js';
import { buildAgent, FakeCLI, FakeLLMProvider, makeTestConfig, tmpDir } from './fakes.js';

const dirs: string[] = [];
function newDir(): string {
  const d = tmpDir();
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

class EchoTool implements Tool {
  calls: Record<string, any>[] = [];
  get name(): string {
    return 'echo';
  }
  get description(): string {
    return 'echo input';
  }
  get inputSchema(): Record<string, any> {
    return { type: 'object', properties: { value: { type: 'string' } }, required: ['value'] };
  }
  async execute(params: Record<string, any>): Promise<string> {
    this.calls.push(params);
    return `echoed: ${params.value}`;
  }
}

describe('AgentLoop', () => {
  it('handles a simple text response', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    llm.setTextResponse('Hello, world!');
    const agent = buildAgent(llm, cli, makeTestConfig(), newDir());

    await agent.processMessage('Hi there');

    const msgs = agent.conversationState.messages;
    expect(msgs).toHaveLength(2);
    expect(msgs[0]!.role).toBe('user');
    expect(msgs[1]!.role).toBe('assistant');
    expect(msgs[1]!.text).toBe('Hello, world!');
  });

  it('runs a tool round-trip', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    const echo = new EchoTool();
    llm.setToolThenText('echo', { value: 'x' }, 'tool_1', 'All done.');
    const agent = buildAgent(llm, cli, makeTestConfig(), newDir(), { extraTools: [echo] });

    await agent.processMessage('use the tool');

    expect(echo.calls).toEqual([{ value: 'x' }]);
    expect(cli.toolResults[0]![0]).toBe('echo');
    const msgs = agent.conversationState.messages;
    // user, assistant(tool_use), user(tool_result), assistant(text)
    expect(msgs).toHaveLength(4);
    expect(msgs[3]!.text).toBe('All done.');
    expect(llm.calls).toHaveLength(2);
  });

  it('runs multiple tools in one turn', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    const echo = new EchoTool();
    llm.setMultiToolResponse(
      [
        ['t1', 'echo', { value: 'a' }],
        ['t2', 'echo', { value: 'b' }],
      ],
      'fin',
    );
    const agent = buildAgent(llm, cli, makeTestConfig(), newDir(), { extraTools: [echo] });
    await agent.processMessage('go');
    expect(echo.calls).toHaveLength(2);
    const toolResultMsg = agent.conversationState.messages[2]!;
    expect(toolResultMsg.content).toHaveLength(2);
  });

  it('records thinking blocks and toggles thinking state', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    const config = makeTestConfig({ reasoning: { enabled: true, show_thinking: true } });
    llm.setThinkingThenText('let me think', 'answer');
    const agent = buildAgent(llm, cli, config, newDir());
    await agent.processMessage('q');
    expect(cli.thinkingStarted).toBe(1);
    expect(cli.thinkingEnded).toBe(1);
    const assistant = agent.conversationState.messages[1]!;
    expect(assistant.content[0]!.type).toBe('thinking');
  });

  it('surfaces tool errors as tool_result with is_error', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    const failing: Tool = {
      name: 'boom',
      description: 'fails',
      inputSchema: { type: 'object', properties: {} },
      async execute() {
        throw new Error('kaboom');
      },
    };
    llm.setToolThenText('boom', {}, 'tid', 'recovered');
    const agent = buildAgent(llm, cli, makeTestConfig(), newDir(), { extraTools: [failing] });
    await agent.processMessage('go');
    const toolResult = agent.conversationState.messages[2]!.content[0]!;
    expect(toolResult.type).toBe('tool_result');
    if (toolResult.type === 'tool_result') {
      expect(toolResult.is_error).toBe(true);
      expect(toolResult.content).toContain('kaboom');
    }
  });

  it('expands @file references', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    const dir = newDir();
    fs.writeFileSync(path.join(dir, 'note.txt'), 'FILE_CONTENTS_HERE');
    llm.setTextResponse('ok');
    const agent = buildAgent(llm, cli, makeTestConfig(), dir);
    await agent.processMessage('look at @note.txt please');
    const userMsg = agent.conversationState.messages[0]!;
    expect(userMsg.text).toContain('FILE_CONTENTS_HERE');
    expect(userMsg.text).toContain('<file path="note.txt">');
  });

  it('syncs total tokens to API input_tokens', async () => {
    const llm = new FakeLLMProvider();
    const cli = new FakeCLI();
    llm.setTextResponse('hi', 1234, 10);
    const agent = buildAgent(llm, cli, makeTestConfig(), newDir());
    await agent.processMessage('q');
    expect(agent.conversationState.totalTokens).toBe(1234);
  });
});
