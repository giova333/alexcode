/** Memory tools: search mem0 and append curated entries to MEMORY.md. */

import type { MemoryManager } from '../../memory/manager.js';
import type { Tool } from '../base.js';

export class MemorySearchTool implements Tool {
  constructor(private memory: MemoryManager) {}

  get name(): string {
    return 'memory_search';
  }

  get description(): string {
    return (
      "Search the agent's persistent mem0 memory (scope is configured via " +
      "memory.scope: 'global' for cross-project, 'project' for this project only). " +
      'Use this to recall facts, decisions, or context from prior turns and prior ' +
      'sessions. Each result is tagged with source matching the configured scope.'
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        query: {
          type: 'string',
          description: 'The search query — can be a question, keywords, or a topic.',
        },
        top_k: {
          type: 'integer',
          description: 'Maximum number of results to return (default: 5).',
          default: 5,
        },
      },
      required: ['query'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    const query: string = params.query;
    const topK: number = typeof params.top_k === 'number' ? params.top_k : 5;
    const results = await this.memory.search(query, topK);
    if (results.length === 0) {
      return 'No matching memories found.';
    }
    return JSON.stringify(results, null, 2);
  }
}

export class MemorySaveTool implements Tool {
  constructor(private memory: MemoryManager) {}

  get name(): string {
    return 'memory_save';
  }

  get description(): string {
    return (
      'Append an entry to MEMORY.md — the human-curated long-term knowledge file ' +
      '(project conventions, user preferences, architecture decisions, durable ' +
      'facts that should persist across sessions). Conversation messages are ' +
      'captured automatically by mem0; use this tool only when something is ' +
      'worth promoting to the curated file.'
    );
  }

  get inputSchema(): Record<string, any> {
    return {
      type: 'object',
      properties: {
        content: {
          type: 'string',
          description: 'The entry to append. Use concise markdown.',
        },
      },
      required: ['content'],
    };
  }

  async execute(params: Record<string, any>): Promise<string> {
    return this.memory.saveMain(params.content);
  }
}
