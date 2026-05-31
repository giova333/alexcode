/** Adapts MCP tools to the internal Tool interface. */

import type { Tool } from '../base.js';
import type { MCPManager } from './client.js';

interface McpToolMeta {
  name: string;
  description?: string;
  inputSchema?: Record<string, any>;
}

/** Wraps an MCP server tool as an internal Tool with automatic reconnection. */
export class MCPToolAdapter implements Tool {
  constructor(
    private session: any,
    private serverName: string,
    private mcpTool: McpToolMeta,
    private manager: MCPManager | null = null,
  ) {}

  get name(): string {
    return `mcp__${this.serverName}__${this.mcpTool.name}`;
  }

  get description(): string {
    return this.mcpTool.description ?? '';
  }

  get inputSchema(): Record<string, any> {
    return this.mcpTool.inputSchema ?? { type: 'object', properties: {} };
  }

  setSession(session: any): void {
    this.session = session;
  }

  async execute(params: Record<string, any>): Promise<string> {
    try {
      return await this.call(params);
    } catch (firstError) {
      if (this.manager === null) {
        throw new Error(
          `MCP tool '${this.mcpTool.name}' on server '${this.serverName}' failed: ${String(firstError)}`,
        );
      }
      const newSession = await this.manager.reconnect(this.serverName);
      if (newSession === null) {
        throw new Error(
          `MCP tool '${this.mcpTool.name}' on server '${this.serverName}' failed and reconnection failed: ${String(firstError)}`,
        );
      }
      this.session = newSession;
      try {
        return await this.call(params);
      } catch (retryError) {
        throw new Error(
          `MCP tool '${this.mcpTool.name}' on server '${this.serverName}' failed after reconnect: ${String(retryError)}`,
        );
      }
    }
  }

  private async call(params: Record<string, any>): Promise<string> {
    const result = await this.session.callTool({ name: this.mcpTool.name, arguments: params });
    const parts: string[] = [];
    for (const content of result.content ?? []) {
      if (content && typeof content === 'object' && 'text' in content) {
        parts.push(String((content as any).text));
      } else {
        parts.push(String(content));
      }
    }
    return parts.join('\n') || '(no output)';
  }
}
