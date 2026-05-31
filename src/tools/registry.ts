/** Central tool registry. */

import type { ToolDefinition } from '../llm/base.js';
import type { Tool } from './base.js';

/** Stores tools and generates API-compatible definitions. */
export class ToolRegistry {
  private tools = new Map<string, Tool>();

  register(tool: Tool): void {
    this.tools.set(tool.name, tool);
  }

  get(name: string): Tool | undefined {
    return this.tools.get(name);
  }

  unregister(name: string): void {
    this.tools.delete(name);
  }

  /** Generate tool definitions in Anthropic API format. */
  allDefinitions(): ToolDefinition[] {
    return [...this.tools.values()].map((tool) => ({
      name: tool.name,
      description: tool.description,
      input_schema: tool.inputSchema,
    }));
  }

  /** Generate tool definitions only for the given set of tool names. */
  definitionsFor(names: Set<string>): ToolDefinition[] {
    return [...this.tools.values()]
      .filter((tool) => names.has(tool.name))
      .map((tool) => ({
        name: tool.name,
        description: tool.description,
        input_schema: tool.inputSchema,
      }));
  }

  /** Create a new registry with all tools except the excluded ones. */
  cloneExcluding(excludeNames: Set<string>): ToolRegistry {
    const registry = new ToolRegistry();
    for (const [name, tool] of this.tools) {
      if (!excludeNames.has(name)) registry.register(tool);
    }
    return registry;
  }

  /** Create a new registry with only the specified tools. */
  cloneIncluding(includeNames: Set<string>): ToolRegistry {
    const registry = new ToolRegistry();
    for (const [name, tool] of this.tools) {
      if (includeNames.has(name)) registry.register(tool);
    }
    return registry;
  }

  listNames(): string[] {
    return [...this.tools.keys()];
  }
}
