/** Plan tool: delegates planning tasks to a read-only subagent with console output. */

import fs from 'node:fs';
import path from 'node:path';

import type { CLI } from '../../cli/types.js';
import type { Config } from '../../config/schema.js';
import type { LLMProvider } from '../../llm/base.js';
import { fillPlaceholders, loadPlanPrompt } from '../../prompts.js';
import { SubagentRunner } from '../../subagent/runner.js';
import type { Tool } from '../base.js';
import { ToolExecutor } from '../executor.js';
import type { ToolRegistry } from '../registry.js';

const PLAN_TOOLS = new Set(['read', 'glob', 'grep', 'bash', 'web_fetch', 'web_search', 'ask_user']);

export class PlanTool implements Tool {
  private planFile: string | null = null;

  constructor(
    private llm: LLMProvider,
    private parentRegistry: ToolRegistry,
    private config: Config,
    private cli: CLI,
  ) {}

  setPlanFile(filePath: string): void {
    this.planFile = filePath;
  }

  get name(): string {
    return 'plan';
  }

  get description(): string {
    return (
      'Delegate a planning task to a specialized read-only agent. ' +
      'The plan agent explores the codebase using read-only tools ' +
      '(read, glob, grep, bash, web_fetch, web_search) and produces ' +
      'a detailed implementation plan. Output is streamed to the console.'
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        task: {
          type: 'string',
          description:
            'The planning task. Describe what you need the plan agent to explore, ' +
            'analyze, and design. The plan agent will explore the codebase using ' +
            'read-only tools and produce an implementation plan.',
        },
      },
      required: ['task'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const task: string = params.task ?? '';
    if (!task) return "Error: 'task' is required.";
    const runner = this.createRunner();
    const result = await runner.run(task);
    this.persistPlan(result);
    return result;
  }

  private persistPlan(planText: string): void {
    if (!this.planFile || !planText) return;
    try {
      fs.mkdirSync(path.dirname(this.planFile), { recursive: true });
      fs.writeFileSync(this.planFile, planText);
    } catch {
      console.error(`Failed to persist plan to ${this.planFile}`);
    }
  }

  private buildSystemPrompt(): string {
    return fillPlaceholders(loadPlanPrompt());
  }

  private createRunner(): SubagentRunner {
    const allowed = new Set(PLAN_TOOLS);
    for (const name of this.parentRegistry.listNames()) {
      if (name.startsWith('mcp__')) allowed.add(name);
    }
    const childRegistry = this.parentRegistry.cloneIncluding(allowed);
    const childExecutor = new ToolExecutor(childRegistry);
    return new SubagentRunner(
      this.llm,
      childRegistry,
      childExecutor,
      this.config,
      this.buildSystemPrompt(),
      this.cli,
    );
  }
}
