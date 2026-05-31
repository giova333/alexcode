import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { SubagentRunner } from '../src/subagent/runner.js';
import { PlanTool } from '../src/tools/builtin/plan.js';
import { SubagentTool } from '../src/tools/builtin/subagent.js';
import type { Tool } from '../src/tools/base.js';
import { ToolExecutor } from '../src/tools/executor.js';
import { ToolRegistry } from '../src/tools/registry.js';
import { FakeCLI, FakeLLMProvider, makeTestConfig, tmpDir } from './fakes.js';

const dirs: string[] = [];
function newDir(): string {
  const d = tmpDir();
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
});

function registryWith(...tools: Tool[]): ToolRegistry {
  const r = new ToolRegistry();
  for (const t of tools) r.register(t);
  return r;
}

const noopTool = (name: string): Tool => ({
  name,
  description: name,
  inputSchema: { type: 'object', properties: {} },
  async execute() {
    return `${name} ran`;
  },
});

describe('SubagentRunner', () => {
  it('runs a task to a text answer', async () => {
    const llm = new FakeLLMProvider();
    llm.setTextResponse('the answer');
    const registry = new ToolRegistry();
    const runner = new SubagentRunner(
      llm,
      registry,
      new ToolExecutor(registry),
      makeTestConfig(),
      'system',
    );
    expect(await runner.run('do it')).toBe('the answer');
  });

  it('executes tools then returns text', async () => {
    const llm = new FakeLLMProvider();
    llm.setToolThenText('read', { file_path: 'x' }, 'tid', 'finished');
    const registry = registryWith(noopTool('read'));
    const runner = new SubagentRunner(
      llm,
      registry,
      new ToolExecutor(registry),
      makeTestConfig(),
      'system',
    );
    expect(await runner.run('go')).toBe('finished');
  });
});

describe('SubagentTool', () => {
  it('excludes subagent/plan/memory_save/ask_user from the child registry', async () => {
    const llm = new FakeLLMProvider();
    llm.setTextResponse('done');
    const parent = registryWith(
      noopTool('read'),
      noopTool('subagent'),
      noopTool('plan'),
      noopTool('memory_save'),
      noopTool('ask_user'),
    );
    const tool = new SubagentTool(llm, parent, makeTestConfig(), 'sys');
    const result = await tool.execute({ action: 'run', task: 'explore' });
    expect(result).toBe('done');
  });

  it('lists launched tasks', async () => {
    const llm = new FakeLLMProvider();
    const tool = new SubagentTool(llm, new ToolRegistry(), makeTestConfig(), 'sys');
    expect(await tool.execute({ action: 'list' })).toBe('No subagents have been launched.');
  });

  it('errors on missing task', async () => {
    const llm = new FakeLLMProvider();
    const tool = new SubagentTool(llm, new ToolRegistry(), makeTestConfig(), 'sys');
    expect(await tool.execute({ action: 'run' })).toContain("'task' is required");
  });
});

describe('PlanTool', () => {
  it('runs read-only and persists the plan file', async () => {
    const llm = new FakeLLMProvider();
    llm.setTextResponse('## Plan\nstep 1');
    const parent = registryWith(noopTool('read'), noopTool('write'), noopTool('edit'));
    const plan = new PlanTool(llm, parent, makeTestConfig(), new FakeCLI());
    const d = newDir();
    const planFile = path.join(d, '.agent', 'plans', 'sess.md');
    plan.setPlanFile(planFile);

    const result = await plan.execute({ task: 'design X' });
    expect(result).toContain('## Plan');
    expect(fs.readFileSync(planFile, 'utf-8')).toContain('step 1');

    // The plan agent's tool definitions should exclude write/edit.
    const toolsSent = llm.calls[0]!.tools as Array<{ name: string }> | null;
    const names = (toolsSent ?? []).map((t) => t.name);
    expect(names).toContain('read');
    expect(names).not.toContain('write');
    expect(names).not.toContain('edit');
  });
});
