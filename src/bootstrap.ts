/** Application initialization and wiring (mirrors __main__._async_main). */

import { CLI } from './cli/cli.js';
import { loadConfig } from './config/config.js';
import type { Config } from './config/schema.js';
import { AgentLoop } from './core/loop.js';
import { HistoryStorage } from './history/storage.js';
import { AnthropicProvider } from './llm/anthropic.js';
import type { LLMProvider } from './llm/base.js';
import { MemoryManager } from './memory/manager.js';
import { Mem0Provider } from './memory/mem0Provider.js';
import type { MemoryProvider } from './memory/provider.js';
import { loadSystemPrompt } from './prompts.js';
import { SkillLoader } from './skills/loader.js';
import { registerBuiltins } from './tools/builtin/index.js';
import { PlanTool } from './tools/builtin/plan.js';
import { SubagentTool } from './tools/builtin/subagent.js';
import { ToolExecutor } from './tools/executor.js';
import { MCPManager } from './tools/mcp/client.js';
import { ToolRegistry } from './tools/registry.js';

export interface CliArgs {
  model?: string | undefined;
  resume?: string | undefined;
}

function createLlmProvider(config: Config): LLMProvider {
  return new AnthropicProvider(config.anthropic, config.model);
}

export async function runApp(args: CliArgs): Promise<void> {
  const projectDir = process.cwd();
  const config = loadConfig(projectDir);

  if (args.model) config.model = args.model;

  const cli = new CLI(projectDir);
  const llm = createLlmProvider(config);

  // Memory (initialize early so tools can reference it).
  let memoryProvider: MemoryProvider | null = null;
  if (config.memory.enabled && config.mem0.enabled) {
    try {
      memoryProvider = new Mem0Provider(config.mem0, config.memory.scope, projectDir);
    } catch (e) {
      cli.printInfo(`mem0 disabled: ${String(e)}`);
    }
  }

  let memoryManager: MemoryManager | null = null;
  if (config.memory.enabled) {
    memoryManager = new MemoryManager(config.memory, projectDir, memoryProvider);
  }

  // Tools.
  const toolRegistry = new ToolRegistry();
  registerBuiltins(toolRegistry, config, cli, memoryManager);
  const toolExecutor = new ToolExecutor(toolRegistry);

  // Subagent tool (registered after builtins so cloneExcluding captures all tools).
  const subagentTool = new SubagentTool(llm, toolRegistry, config, loadSystemPrompt(), cli);
  toolRegistry.register(subagentTool);

  // MCP servers.
  const mcpManager = new MCPManager(toolRegistry);
  if (config.mcp_servers.length > 0) {
    cli.printInfo('Connecting to MCP servers...');
    const connected = await mcpManager.connectAll(config.mcp_servers);
    if (connected.length > 0) cli.printInfo(`Connected: ${connected.join(', ')}`);
  }

  // Plan tool (registered after MCP so it can see MCP tools in the parent registry).
  const planTool = new PlanTool(llm, toolRegistry, config, cli);
  toolRegistry.register(planTool);

  // History.
  const history = new HistoryStorage(config.history.dir, projectDir);

  // Skills.
  const skillLoader = new SkillLoader(config.skills.dirs, projectDir);
  const skills = skillLoader.loadAll();
  cli.setSkills(
    skills.filter((s) => s.userInvocable).map((s) => [s.name, s.description || s.name]),
  );

  const loop = new AgentLoop({
    config,
    llm,
    cli,
    projectDir,
    toolRegistry,
    toolExecutor,
    memoryManager,
    history,
    skillLoader,
    skills,
    planTool,
  });

  // Resume a previous session if requested.
  if (args.resume) {
    const sessionId =
      args.resume === '__latest__'
        ? history.getLatestSessionId()
        : history.findSession(args.resume);
    if (sessionId && loop.resumeSession(sessionId)) {
      const msgCount = loop.conversationState.messages.length;
      cli.printInfo(`Resumed session: ${sessionId} (${msgCount} messages)`);
    } else {
      cli.printError(
        args.resume === '__latest__'
          ? 'No previous sessions.'
          : `Session not found: ${args.resume}`,
      );
    }
  }

  try {
    await loop.run();
  } finally {
    await mcpManager.close();
    if (memoryProvider !== null) await memoryProvider.close();
    cli.close();
  }
}
