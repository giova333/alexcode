/** MCP server connection manager. */

import type { McpServerConfig } from '../../config/schema.js';
import type { ToolRegistry } from '../registry.js';
import { MCPToolAdapter } from './adapter.js';
import { FileOAuthProvider, waitForCallback } from './oauth.js';

function interpolate(value: string): string {
  return value.replace(/\$\{(\w+)}/g, (_m, name: string) => process.env[name] ?? '');
}

function interpolateRecord(rec: Record<string, string> = {}): Record<string, string> {
  const out: Record<string, string> = {};
  for (const [k, v] of Object.entries(rec)) {
    out[k] = typeof v === 'string' ? interpolate(v) : v;
  }
  return out;
}

/** Manages connections to multiple MCP servers with automatic reconnection. */
export class MCPManager {
  private clients = new Map<string, any>();
  private configs = new Map<string, McpServerConfig>();

  constructor(private registry: ToolRegistry) {}

  /** Connect to all configured MCP servers. Returns connected server names. */
  async connectAll(serverConfigs: McpServerConfig[]): Promise<string[]> {
    const connected: string[] = [];
    for (const config of serverConfigs) {
      const name = config.name ?? 'unknown';
      try {
        await this.connectOne(config);
        connected.push(name);
      } catch (e) {
        console.error(`Warning: Failed to connect MCP server '${name}': ${String(e)}`);
      }
    }
    return connected;
  }

  /** Reconnect a single MCP server. Returns new client/session or null. */
  async reconnect(serverName: string): Promise<any | null> {
    const config = this.configs.get(serverName);
    if (!config) return null;
    await this.closeServer(serverName);
    try {
      await this.connectOne(config);
      return this.clients.get(serverName) ?? null;
    } catch {
      return null;
    }
  }

  private async connectOne(config: McpServerConfig): Promise<void> {
    const name = config.name ?? 'unknown';
    const transport = config.transport ?? 'stdio';
    this.configs.set(name, config);

    const { Client } = (await import('@modelcontextprotocol/sdk/client/index.js')) as any;
    const client = new Client({ name: 'alexcode', version: '0.1.0' }, { capabilities: {} });

    if (transport === 'stdio') {
      await this.connectStdio(client, config);
    } else if (transport === 'http' || transport === 'streamable-http') {
      await this.connectHttp(client, config);
    } else {
      throw new Error(`Unsupported MCP transport: ${transport}`);
    }

    this.clients.set(name, client);

    const toolsResult = await client.listTools();
    for (const tool of toolsResult.tools ?? []) {
      this.registry.register(new MCPToolAdapter(client, name, tool, this));
    }
  }

  private async connectStdio(client: any, config: McpServerConfig): Promise<void> {
    const { StdioClientTransport } =
      (await import('@modelcontextprotocol/sdk/client/stdio.js')) as any;
    const resolvedEnv = interpolateRecord(config.env);
    const transport = new StdioClientTransport({
      command: config.command,
      args: config.args ?? [],
      env: { ...process.env, ...resolvedEnv },
    });
    await client.connect(transport);
  }

  private async connectHttp(client: any, config: McpServerConfig): Promise<void> {
    const url = config.url!;
    const name = config.name ?? 'unknown';
    const headers = interpolateRecord(config.headers);

    const { StreamableHTTPClientTransport } =
      (await import('@modelcontextprotocol/sdk/client/streamableHttp.js')) as any;
    const authMod = (await import('@modelcontextprotocol/sdk/client/auth.js')) as any;

    const authProvider = new FileOAuthProvider(name);
    const makeTransport = () =>
      new StreamableHTTPClientTransport(new URL(url), {
        authProvider,
        requestInit: Object.keys(headers).length > 0 ? { headers } : undefined,
      });

    let transport = makeTransport();
    try {
      await client.connect(transport);
    } catch (e) {
      const UnauthorizedError = authMod.UnauthorizedError;
      if (UnauthorizedError && e instanceof UnauthorizedError) {
        const [code] = await waitForCallback();
        await transport.finishAuth(code);
        transport = makeTransport();
        await client.connect(transport);
      } else {
        throw e;
      }
    }
  }

  private async closeServer(name: string): Promise<void> {
    const client = this.clients.get(name);
    this.clients.delete(name);
    if (client) {
      try {
        await client.close();
      } catch {
        /* ignore */
      }
    }
    const prefix = `mcp__${name}__`;
    for (const toolName of this.registry.listNames()) {
      if (toolName.startsWith(prefix)) this.registry.unregister(toolName);
    }
  }

  async close(): Promise<void> {
    for (const name of [...this.clients.keys()]) {
      await this.closeServer(name);
    }
  }
}
