/** Tool call dispatcher. */

import { ToolError } from './base.js';
import type { ToolRegistry } from './registry.js';

/** Looks up and executes tools from the registry. */
export class ToolExecutor {
  constructor(private registry: ToolRegistry) {}

  async execute(name: string, params: Record<string, any>): Promise<string> {
    const tool = this.registry.get(name);
    if (tool === undefined) {
      throw new ToolError(`Unknown tool: ${name}`);
    }
    return tool.execute(params);
  }
}
