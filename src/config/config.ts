/** Configuration loading with YAML and environment variable interpolation. */

import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { parse as parseYaml } from 'yaml';

import { CONFIG_DEFAULT_PATH } from '../paths.js';
import { buildConfig, type Config, type McpServerConfig } from './schema.js';

function interpolateEnv(value: string): string {
  return value.replace(/\$\{(\w+)}/g, (_match, name: string) => process.env[name] ?? '');
}

function interpolateRecursive(obj: unknown): unknown {
  if (typeof obj === 'string') return interpolateEnv(obj);
  if (Array.isArray(obj)) return obj.map(interpolateRecursive);
  if (obj && typeof obj === 'object') {
    const out: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(obj)) out[k] = interpolateRecursive(v);
    return out;
  }
  return obj;
}

function loadYaml(filePath: string): Record<string, any> {
  const text = fs.readFileSync(filePath, 'utf-8');
  return (parseYaml(text) as Record<string, any>) ?? {};
}

function isObject(value: unknown): value is Record<string, any> {
  return !!value && typeof value === 'object' && !Array.isArray(value);
}

/** Merge override into base in-place, recursing into plain objects. */
function deepMerge(base: Record<string, any>, override: Record<string, any>): void {
  for (const [key, value] of Object.entries(override)) {
    if (key in base && isObject(base[key]) && isObject(value)) {
      deepMerge(base[key], value);
    } else {
      base[key] = value;
    }
  }
}

/**
 * Load MCP servers from a Claude Code-style mcp.json file.
 *
 * Converts {"mcpServers": {"name": {"type": "stdio", ...}}} to the internal
 * list form [{"name": "name", "transport": "stdio", ...}].
 */
function loadMcpJson(filePath: string): McpServerConfig[] {
  if (!fs.existsSync(filePath)) return [];
  let data: Record<string, any>;
  try {
    data = JSON.parse(fs.readFileSync(filePath, 'utf-8'));
  } catch {
    return [];
  }

  const servers = data.mcpServers;
  if (!isObject(servers)) return [];

  const result: McpServerConfig[] = [];
  for (const [name, raw] of Object.entries(servers)) {
    if (!isObject(raw)) continue;
    const entry: McpServerConfig = { name };
    entry.transport = raw.type ?? raw.transport ?? 'stdio';
    for (const key of ['command', 'args', 'env', 'url', 'headers'] as const) {
      if (key in raw) (entry as Record<string, any>)[key] = raw[key];
    }
    result.push(entry);
  }
  return result;
}

/** Load config by merging default -> project -> user configs. */
export function loadConfig(projectDir?: string): Config {
  let merged: Record<string, any> = {};

  // 1. Default config (bundled with package)
  if (fs.existsSync(CONFIG_DEFAULT_PATH)) {
    merged = loadYaml(CONFIG_DEFAULT_PATH);
  }

  // 2. Project config
  if (projectDir) {
    const projectCfg = path.join(projectDir, 'config.yaml');
    if (fs.existsSync(projectCfg)) deepMerge(merged, loadYaml(projectCfg));
  }

  // 3. User config
  const userCfg = path.join(os.homedir(), '.config', 'agent', 'config.yaml');
  if (fs.existsSync(userCfg)) deepMerge(merged, loadYaml(userCfg));

  // 4. MCP servers from .agent/mcp.json (overrides YAML entries by name)
  if (projectDir) {
    const mcpServers = loadMcpJson(path.join(projectDir, '.agent', 'mcp.json'));
    if (mcpServers.length > 0) {
      const existing: McpServerConfig[] = merged.mcp_servers ?? [];
      const jsonNames = new Set(mcpServers.map((s) => s.name));
      const deduped = existing.filter((s) => !jsonNames.has(s.name));
      deduped.push(...mcpServers);
      merged.mcp_servers = deduped;
    }
  }

  // 5. Interpolate env vars
  merged = interpolateRecursive(merged) as Record<string, any>;

  return buildConfig(merged);
}
