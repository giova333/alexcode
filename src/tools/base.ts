/** Tool interface definition. */

import type { ToolDefinition } from '../llm/base.js';

/** Every tool (built-in, MCP, skill) implements this interface. */
export interface Tool {
  readonly name: string;
  readonly description: string;
  readonly inputSchema: Record<string, any>;
  execute(params: Record<string, any>): Promise<string>;
}

/** Raised when a tool execution fails. */
export class ToolError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'ToolError';
  }
}

export type { ToolDefinition };
