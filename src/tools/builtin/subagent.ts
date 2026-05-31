/** Subagent tool for task delegation with sync and async execution. */

import type { CLI } from '../../cli/types.js';
import type { Config } from '../../config/schema.js';
import type { LLMProvider } from '../../llm/base.js';
import { fillPlaceholders } from '../../prompts.js';
import { SubagentRunner } from '../../subagent/runner.js';
import type { Tool } from '../base.js';
import { ToolExecutor } from '../executor.js';
import type { ToolRegistry } from '../registry.js';

const EXCLUDED_TOOLS = new Set(['subagent', 'plan', 'memory_save', 'ask_user']);

interface TaskRecord {
  promise: Promise<string>;
  status: 'running' | 'completed' | 'failed';
  result?: string;
  error?: unknown;
}

/** Tracks async subagent tasks and their results. */
export class SubagentManager {
  private tasks = new Map<string, TaskRecord>();
  private counter = 0;

  launch(promiseFactory: () => Promise<string>): string {
    this.counter += 1;
    const taskId = `subagent-${this.counter}`;
    const record: TaskRecord = { promise: Promise.resolve(''), status: 'running' };
    record.promise = promiseFactory()
      .then((result) => {
        record.status = 'completed';
        record.result = result;
        return result;
      })
      .catch((err) => {
        record.status = 'failed';
        record.error = err;
        throw err;
      });
    // Avoid unhandled rejection warnings; status/result is read via getResult.
    record.promise.catch(() => undefined);
    this.tasks.set(taskId, record);
    return taskId;
  }

  getResult(taskId: string): string {
    const task = this.tasks.get(taskId);
    if (task === undefined) return `Unknown task_id: ${taskId}`;
    if (task.status === 'running') return 'Status: running';
    if (task.status === 'failed') {
      return `Status: failed\nError: ${String((task.error as any)?.message ?? task.error)}`;
    }
    return `Status: completed\nResult:\n${task.result ?? ''}`;
  }

  listTasks(): Array<{ task_id: string; status: string }> {
    return [...this.tasks.entries()].map(([taskId, task]) => ({
      task_id: taskId,
      status: task.status,
    }));
  }
}

export class SubagentTool implements Tool {
  private manager = new SubagentManager();

  constructor(
    private llm: LLMProvider,
    private parentRegistry: ToolRegistry,
    private config: Config,
    private defaultSystemPrompt: string,
    private cli: CLI | null = null,
  ) {}

  get name(): string {
    return 'subagent';
  }

  get description(): string {
    return (
      'Delegate a task to an independent subagent. The subagent has its own ' +
      'conversation and access to all tools (except subagent, memory_save, ' +
      "ask_user). Supports synchronous ('run') and asynchronous ('launch'/" +
      "'check'/'list') execution."
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        action: {
          type: 'string',
          enum: ['run', 'launch', 'check', 'list'],
          description:
            "'run' executes synchronously and returns the result. " +
            "'launch' starts an async subagent and returns a task_id. " +
            "'check' retrieves the result of an async subagent by task_id. " +
            "'list' shows all tracked async subagents.",
        },
        task: {
          type: 'string',
          description:
            "The task description for the subagent. Required for 'run' and 'launch' actions.",
        },
        system_prompt: {
          type: 'string',
          description:
            'Optional custom system prompt for the subagent. ' +
            'If omitted, the default agent system prompt is used.',
        },
        task_id: {
          type: 'string',
          description: "The task_id to check. Required for 'check' action.",
        },
      },
      required: ['action'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const action: string = params.action ?? '';
    const task: string = params.task ?? '';
    const systemPrompt: string = params.system_prompt || this.buildSystemPrompt();
    const taskId: string = params.task_id ?? '';

    if (action === 'run') {
      if (!task) return "Error: 'task' is required for 'run' action.";
      return this.createRunner(systemPrompt).run(task);
    } else if (action === 'launch') {
      if (!task) return "Error: 'task' is required for 'launch' action.";
      const tid = this.manager.launch(() => this.createRunner(systemPrompt).run(task));
      return `Subagent launched with task_id: ${tid}`;
    } else if (action === 'check') {
      if (!taskId) return "Error: 'task_id' is required for 'check' action.";
      return this.manager.getResult(taskId);
    } else if (action === 'list') {
      const tasks = this.manager.listTasks();
      if (tasks.length === 0) return 'No subagents have been launched.';
      return JSON.stringify(tasks, null, 2);
    }

    return `Error: Unknown action '${action}'. Use 'run', 'launch', 'check', or 'list'.`;
  }

  private buildSystemPrompt(): string {
    return fillPlaceholders(this.defaultSystemPrompt);
  }

  private createRunner(systemPrompt: string): SubagentRunner {
    const childRegistry = this.parentRegistry.cloneExcluding(EXCLUDED_TOOLS);
    const childExecutor = new ToolExecutor(childRegistry);
    return new SubagentRunner(
      this.llm,
      childRegistry,
      childExecutor,
      this.config,
      systemPrompt,
      this.cli,
    );
  }
}
