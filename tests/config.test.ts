import { afterEach, describe, expect, it } from 'vitest';
import fs from 'node:fs';
import path from 'node:path';

import { loadConfig } from '../src/config/config.js';
import { buildConfig } from '../src/config/schema.js';
import { tmpDir } from './fakes.js';

const dirs: string[] = [];
function newDir(): string {
  const d = tmpDir();
  dirs.push(d);
  return d;
}
afterEach(() => {
  for (const d of dirs.splice(0)) fs.rmSync(d, { recursive: true, force: true });
  delete process.env.TEST_API_KEY;
});

describe('buildConfig', () => {
  it('applies defaults', () => {
    const c = buildConfig({});
    expect(c.provider).toBe('anthropic');
    expect(c.max_tokens).toBe(8192);
    expect(c.compaction.threshold_tokens).toBe(80000);
    expect(c.tools.web_fetch.timeout).toBe(30);
    expect(c.mem0.embedder.provider).toBe('openai');
  });

  it('respects overrides without losing nested defaults', () => {
    const c = buildConfig({ tools: { bash_timeout: 5 } });
    expect(c.tools.bash_timeout).toBe(5);
    expect(c.tools.web_search.provider).toBe('brave');
  });
});

describe('loadConfig', () => {
  it('deep merges a project config over defaults', () => {
    const d = newDir();
    fs.writeFileSync(path.join(d, 'config.yaml'), 'model: my-model\nmax_tokens: 42\n');
    const c = loadConfig(d);
    expect(c.model).toBe('my-model');
    expect(c.max_tokens).toBe(42);
  });

  it('interpolates ${ENV} references', () => {
    process.env.TEST_API_KEY = 'secret-123';
    const d = newDir();
    fs.writeFileSync(path.join(d, 'config.yaml'), 'anthropic:\n  api_key: "${TEST_API_KEY}"\n');
    const c = loadConfig(d);
    expect(c.anthropic.api_key).toBe('secret-123');
  });

  it('loads MCP servers from .agent/mcp.json (Claude Code format)', () => {
    const d = newDir();
    fs.mkdirSync(path.join(d, '.agent'), { recursive: true });
    fs.writeFileSync(
      path.join(d, '.agent', 'mcp.json'),
      JSON.stringify({
        mcpServers: {
          github: { type: 'stdio', command: 'node', args: ['server.js'] },
        },
      }),
    );
    const c = loadConfig(d);
    expect(c.mcp_servers).toHaveLength(1);
    expect(c.mcp_servers[0]).toMatchObject({
      name: 'github',
      transport: 'stdio',
      command: 'node',
      args: ['server.js'],
    });
  });
});
