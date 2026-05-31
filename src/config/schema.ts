/**
 * Configuration schema and types.
 *
 * Config keys are kept in snake_case to match the YAML/JSON files they are
 * loaded from (an external boundary); the rest of the code uses camelCase.
 */

export interface AnthropicConfig {
  api_key: string;
}

export interface ReasoningConfig {
  enabled: boolean;
  /** low, medium, high, xhigh, max, auto (adaptive thinking) */
  effort: string;
  show_thinking: boolean;
}

export interface CompactionConfig {
  threshold_tokens: number;
  keep_recent_messages: number;
}

export interface MemoryConfig {
  enabled: boolean;
  memory_file: string;
  /** "global" (cross-project) or "project" (this project only) */
  scope: string;
}

export interface Mem0LLMConfig {
  provider: string;
  model: string;
  api_key: string;
}

export interface Mem0EmbedderConfig {
  provider: string;
  model: string;
  api_key: string;
}

export interface Mem0Config {
  enabled: boolean;
  project_store_dir: string;
  global_store_dir: string;
  llm: Mem0LLMConfig;
  embedder: Mem0EmbedderConfig;
}

export interface HistoryConfig {
  dir: string;
}

export interface SkillsConfig {
  dirs: string[];
}

export interface WebFetchConfig {
  timeout: number;
  max_content_length: number;
  user_agent: string;
}

export interface WebSearchConfig {
  provider: string;
  api_key: string;
  max_results: number;
}

export interface ToolsConfig {
  bash_timeout: number;
  web_fetch: WebFetchConfig;
  web_search: WebSearchConfig;
}

export interface McpServerConfig {
  name: string;
  transport?: string;
  command?: string;
  args?: string[];
  env?: Record<string, string>;
  url?: string;
  headers?: Record<string, string>;
}

export interface Config {
  provider: string;
  model: string;
  max_tokens: number;
  anthropic: AnthropicConfig;
  reasoning: ReasoningConfig;
  compaction: CompactionConfig;
  memory: MemoryConfig;
  mem0: Mem0Config;
  history: HistoryConfig;
  skills: SkillsConfig;
  tools: ToolsConfig;
  mcp_servers: McpServerConfig[];
}

const USER_AGENT = 'Mozilla/5.0 (compatible; AgentCLI/0.1)';

/** Build a fully-populated Config from a (possibly partial) raw object. */
export function buildConfig(data: Record<string, any> = {}): Config {
  const anthropic = data.anthropic ?? {};
  const reasoning = data.reasoning ?? {};
  const compaction = data.compaction ?? {};
  const memory = data.memory ?? {};
  const mem0 = data.mem0 ?? {};
  const mem0Llm = mem0.llm ?? {};
  const mem0Embedder = mem0.embedder ?? {};
  const history = data.history ?? {};
  const skills = data.skills ?? {};
  const tools = data.tools ?? {};
  const webFetch = tools.web_fetch ?? {};
  const webSearch = tools.web_search ?? {};

  return {
    provider: data.provider ?? 'anthropic',
    model: data.model ?? 'claude-sonnet-4-6',
    max_tokens: data.max_tokens ?? 8192,
    anthropic: {
      api_key: anthropic.api_key ?? '',
    },
    reasoning: {
      enabled: reasoning.enabled ?? false,
      effort: reasoning.effort ?? 'high',
      show_thinking: reasoning.show_thinking ?? false,
    },
    compaction: {
      threshold_tokens: compaction.threshold_tokens ?? 80000,
      keep_recent_messages: compaction.keep_recent_messages ?? 10,
    },
    memory: {
      enabled: memory.enabled ?? true,
      memory_file: memory.memory_file ?? '~/.config/agent/MEMORY.md',
      scope: memory.scope ?? 'global',
    },
    mem0: {
      enabled: mem0.enabled ?? true,
      project_store_dir: mem0.project_store_dir ?? '.agent/mem0/project/',
      global_store_dir: mem0.global_store_dir ?? '~/.config/agent/mem0/global/',
      llm: {
        provider: mem0Llm.provider ?? 'anthropic',
        model: mem0Llm.model ?? 'claude-haiku-4-5',
        api_key: mem0Llm.api_key ?? '',
      },
      embedder: {
        provider: mem0Embedder.provider ?? 'openai',
        model: mem0Embedder.model ?? 'text-embedding-3-small',
        api_key: mem0Embedder.api_key ?? '',
      },
    },
    history: {
      dir: history.dir ?? '.agent/history/',
    },
    skills: {
      dirs: skills.dirs ?? ['skills/'],
    },
    tools: {
      bash_timeout: tools.bash_timeout ?? 120,
      web_fetch: {
        timeout: webFetch.timeout ?? 30,
        max_content_length: webFetch.max_content_length ?? 50_000,
        user_agent: webFetch.user_agent ?? USER_AGENT,
      },
      web_search: {
        provider: webSearch.provider ?? 'brave',
        api_key: webSearch.api_key ?? '',
        max_results: webSearch.max_results ?? 5,
      },
    },
    mcp_servers: data.mcp_servers ?? [],
  };
}
