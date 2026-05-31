/** Register all built-in tools. */

import type { CLI } from '../../cli/types.js';
import type { Config } from '../../config/schema.js';
import type { MemoryManager } from '../../memory/manager.js';
import type { ToolRegistry } from '../registry.js';
import { AskUserTool } from './askUser.js';
import { BashTool } from './bash.js';
import { EditTool } from './edit.js';
import { GlobTool } from './glob.js';
import { GrepTool } from './grep.js';
import { MemorySaveTool, MemorySearchTool } from './memory.js';
import { ReadTool } from './read.js';
import { WebFetchTool } from './webFetch.js';
import { WebSearchTool } from './webSearch.js';
import { WriteTool } from './write.js';

export function registerBuiltins(
  registry: ToolRegistry,
  config: Config,
  cli: CLI,
  memoryManager: MemoryManager | null = null,
): void {
  registry.register(new BashTool(config.tools.bash_timeout));
  registry.register(new ReadTool());
  registry.register(new WriteTool());
  registry.register(new EditTool());
  registry.register(new GlobTool());
  registry.register(new GrepTool());
  registry.register(new AskUserTool(cli));
  registry.register(
    new WebFetchTool(
      config.tools.web_fetch.timeout,
      config.tools.web_fetch.max_content_length,
      config.tools.web_fetch.user_agent,
    ),
  );
  registry.register(
    new WebSearchTool(
      config.tools.web_search.provider,
      config.tools.web_search.api_key,
      config.tools.web_search.max_results,
    ),
  );

  if (memoryManager !== null) {
    registry.register(new MemorySearchTool(memoryManager));
    registry.register(new MemorySaveTool(memoryManager));
  }
}
