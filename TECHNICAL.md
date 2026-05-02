# Technical Documentation

## Architecture Overview

The agent is an async Python CLI application that orchestrates LLM conversations with tool use, persistent memory, and extensible skills. It follows a streaming-first, protocol-based architecture built on `asyncio`.

```
User Input
    |
    v
AgentLoop (core/loop.py)
    |
    +---> /command? ---> Handle built-in or skill invocation
    |
    +---> Check compaction threshold
    |         |
    |         +---> Compactor: summarize old messages + truncate oversized tool results
    |
    +---> Build system prompt (SYSTEM.md + AGENTS.md + MEMORY.md + skill metadata + plan-mode block if toggled)
    |
    +---> Stream LLM response (Anthropic)
    |         |
    |         +---> TextDelta ---> Print to terminal
    |         +---> ThinkingDelta ---> Print if enabled
    |         +---> ToolUseEvent ---> Execute tool ---> Append result ---> Loop back
    |         +---> ResponseComplete ---> Usage info
    |
    +---> Save history (JSONL)

  Conversation.append (every message)
        |
        v
  on_append callback ---> Mem0Client.enqueue_message ---> asyncio.Queue
                                                              |
                                                              v
                                                   Background worker (asyncio.to_thread)
                                                              |
                                                              v
                                                       mem0.Memory.add(...)
```

### Initialization Flow (`__main__.py`)

1. Configure logging (level from `AGENT_LOG_LEVEL`, defaults to `ERROR`; tamps down noisy third-party loggers)
2. Parse CLI args (`--model`, `--resume`)
3. Load config: `config.default.yaml` -> project `config.yaml` -> user `~/.config/agent/config.yaml`
4. Override with CLI args
5. Create LLM provider (Anthropic)
6. Initialize CLI (Rich console + prompt_toolkit)
7. Create `Mem0Client` and `MemoryManager` (if `memory.enabled` and `mem0.enabled`); `Mem0Client` failures are non-fatal
8. Create `ToolRegistry` + register built-in tools (including `web_fetch`, `web_search`)
9. Register `SubagentTool` (after builtins, so clone captures all tools)
10. Connect MCP servers + register MCP tools
11. Register `PlanTool` (after MCP, so it can see MCP tools in parent registry)
12. Discover skills
13. Create `AgentLoop` with all components — wires `memory_manager.handle_message_appended` into `Conversation.on_append`
14. Resume session if `--resume` flag provided
15. Run loop; on shutdown, drain `Mem0Client` worker via `aclose()`

---

## Directory Structure

```
src/agent/
    __init__.py
    __main__.py             # Entry point, arg parsing, async setup
    cli.py                  # Terminal I/O (Rich + prompt_toolkit)
    config.py               # YAML config loading, dataclass hierarchy
    core/
        loop.py             # Main agent loop, LLM cycle, command dispatch
        message.py          # Message dataclass (role, content blocks, tokens)
        conversation.py     # Conversation state (messages, system prompt, token count)
        tokens.py           # Token counting (tiktoken cl100k_base)
    llm/
        base.py             # LLM provider protocol, stream event types
        anthropic.py        # Anthropic Claude provider (extended thinking)
    tools/
        base.py             # Tool protocol + ToolError exception
        registry.py         # Dict-based tool registry (clone_excluding/clone_including)
        executor.py         # Tool dispatch (lookup + execute)
        builtin/
            __init__.py     # register_builtins()
            bash.py         # Shell command execution
            read.py         # File reading with line numbers
            write.py        # File writing
            edit.py         # Find-and-replace editing
            glob_tool.py    # File pattern matching
            grep.py         # Content search (ripgrep/grep)
            ask_user.py     # Interactive user input
            web_fetch.py    # URL content fetching (HTML/JSON/text)
            web_search.py   # Web search (Brave/DuckDuckGo)
            subagent.py     # Sub-agent task delegation (sync/async)
            plan.py         # Read-only planning via sub-agent
            memory_tool.py  # Memory search/save/read tools
        mcp/
            adapter.py      # Wraps MCP tool as internal Tool
            client.py       # MCP server connection manager (stdio)
    subagent/
        __init__.py
        runner.py           # Isolated LLM cycle for sub-agent execution
    memory/
        manager.py          # Orchestrator: MEMORY.md I/O + delegate search/ingest to Mem0Client
        files.py            # MEMORY.md file I/O (expands ~ / abs paths)
        mem0_client.py      # mem0 wrapper: lazy init, async ingestion queue, search
    skills/
        skill.py            # Skill data model, rendering, arg substitution
        loader.py           # Skill discovery + YAML frontmatter parsing
    compaction/
        compactor.py        # Conversation compression (extract + summarize)
    history/
        storage.py          # JSON conversation persistence

prompts/
    SYSTEM.md               # Base system prompt
    PLAN.md                 # Plan mode system prompt (read-only exploration)

.agent/                     # Per-project state (created on first run)
    mcp.json                # MCP server config (Claude Code format)
    plans/                  # Session plan files (<session_id>.md)
    history/                # JSONL session logs
    mem0/project/           # Chroma vector store (only when memory.scope == "project")

~/.config/agent/            # User-scoped state (created on first run)
    config.yaml             # Optional user override
    MEMORY.md               # Curated long-term knowledge (auto-loaded into system prompt)
    input_history           # prompt_toolkit input history
    mem0/global/            # Chroma vector store (only when memory.scope == "global", the default)

AGENTS.md                   # Project-level agent instructions (loaded into system prompt)
config.default.yaml         # Bundled defaults
```

---

## Configuration

### Loading Order (lowest to highest precedence)

1. `config.default.yaml` (bundled defaults)
2. `./config.yaml` (project-level override)
3. `~/.config/agent/config.yaml` (user-level override)
4. `.agent/mcp.json` (Claude Code format MCP servers, merged with YAML `mcp_servers`)
5. CLI args (`--model`, `--resume`)

Configs are deep-merged: nested keys from higher-precedence files override lower ones. Environment variables are interpolated via `${VAR_NAME}` syntax (recursive, empty string fallback).

### Config Dataclass Hierarchy

```python
Config
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    prompts_dir: str = "prompts/"
    anthropic: AnthropicConfig
        api_key: str = "${ANTHROPIC_API_KEY}"
    reasoning: ReasoningConfig
        enabled: bool = True
        effort: str = "high"            # low, medium, high (adaptive thinking)
        show_thinking: bool = True
    compaction: CompactionConfig
        threshold_tokens: int = 80000
        keep_recent_messages: int = 10
    memory: MemoryConfig
        enabled: bool = True
        memory_file: str = "~/.config/agent/MEMORY.md"
        scope: str = "global"           # "global" or "project"
    mem0: Mem0Config
        enabled: bool = True
        project_store_dir: str = ".agent/mem0/project/"
        global_store_dir: str = "~/.config/agent/mem0/global/"
        llm: Mem0LLMConfig
            provider: str = "anthropic"
            model: str = "claude-haiku-4-5"
            api_key: str = "${ANTHROPIC_API_KEY}"
        embedder: Mem0EmbedderConfig
            provider: str = "openai"
            model: str = "text-embedding-3-small"
            api_key: str = "${OPENAI_API_KEY}"
    history: HistoryConfig
        dir: str = ".agent/history/"
    skills: SkillsConfig
        dirs: list[str] = ["skills/"]
    tools: ToolsConfig
        bash_timeout: int = 120
        web_fetch: WebFetchConfig
            timeout: int = 30
            max_content_length: int = 50_000
            user_agent: str = "Mozilla/5.0 (compatible; AgentCLI/0.1)"
        web_search: WebSearchConfig
            provider: str = "brave"
            api_key: str = ""
            max_results: int = 5
    mcp_servers: list[dict] = []
```

### Default Config (`config.default.yaml`)

```yaml
provider: anthropic
model: claude-sonnet-4-6
max_tokens: 8192
prompts_dir: prompts/

anthropic:
  api_key: "${ANTHROPIC_API_KEY}"

reasoning:
  enabled: true
  effort: high               # low, medium, high (adaptive thinking)
  show_thinking: true

compaction:
  threshold_tokens: 80000
  keep_recent_messages: 10

memory:
  enabled: true
  memory_file: ~/.config/agent/MEMORY.md   # user-scoped; one file across all projects
  scope: global                            # "global" (cross-project) or "project" (this project only)

mem0:
  enabled: true
  project_store_dir: .agent/mem0/project/
  global_store_dir: ~/.config/agent/mem0/global/
  llm:
    provider: anthropic
    model: claude-haiku-4-5
    api_key: "${ANTHROPIC_API_KEY}"
  embedder:
    provider: openai
    model: text-embedding-3-small
    api_key: "${OPENAI_API_KEY}"

history:
  dir: .agent/history/

skills:
  dirs:
    - skills/

mcp_servers: []

tools:
  bash_timeout: 120
```

---

## LLM Integration

### Provider Protocol (`llm/base.py`)

The provider implements a streaming protocol:

```python
class LLMProvider(Protocol):
    async def stream(
        system: str,
        messages: list[dict],
        tools: list[dict] | None = None,
        max_tokens: int = 8192,
        reasoning: ReasoningConfig | None = None,
    ) -> AsyncIterator[StreamEvent]
```

**Stream event types:**

| Event | Fields | Description |
|-------|--------|-------------|
| `TextDelta` | `text` | Streamed text chunk |
| `ThinkingDelta` | `text` | Extended thinking chunk |
| `ToolUseEvent` | `id`, `name`, `input` | Tool invocation request |
| `ResponseComplete` | `usage`, `stop_reason` | End signal with token counts |

### Anthropic Provider (`llm/anthropic.py`)

- Client: `anthropic.AsyncAnthropic`
- Streaming: `messages.stream()` async context manager
- Events processed: `content_block_start`, `content_block_delta`, `content_block_stop`
- Tool use: accumulates `input_json_delta` chunks, parses JSON on `content_block_stop`
- Adaptive thinking: sends `thinking.type = "adaptive"` with `output_config.effort` (`low`, `medium`, or `high`)

### Message Format (`core/message.py`)

Messages use Anthropic's content block format internally:

```python
Message(
    role="assistant",
    content=[
        {"type": "text", "text": "Let me check that file."},
        {"type": "tool_use", "id": "toolu_01", "name": "read", "input": {"file_path": "/app.py"}},
    ],
    token_count=42,
)
```

Tool results:
```python
Message(
    role="user",
    content=[
        {"type": "tool_result", "tool_use_id": "toolu_01", "content": "...", "is_error": False}
    ]
)
```

### Token Counting (`core/tokens.py`)

- Uses `tiktoken` with `cl100k_base` encoding
- `count_tokens(text)` — encode length
- `count_message_tokens(message_dict)` — content + 4 token overhead per message
- Tool use/result blocks estimated via JSON serialization length

---

## Core Agent Loop (`core/loop.py`)

### LLM Cycle (`_run_llm_cycle`)

The core loop that drives agentic behavior:

1. Build system prompt: `SYSTEM.md` + `AGENTS.md` + memory context + skill metadata + plan-mode block (if `/plan` is toggled)
2. Get tool definitions from registry
3. Stream LLM response
4. Collect text blocks and tool use events
5. Build assistant message from collected blocks
6. If tool uses exist:
   - Execute each tool via `ToolExecutor`
   - Create `tool_result` message for each
   - Append to conversation
   - **Loop back to step 3** (LLM sees tool results)
7. If no tool uses: return (LLM produced final text response)

There is no iteration limit — the LLM cycle continues until the model produces a text-only response.

### Built-in Commands

| Command | Action |
|---------|--------|
| `/exit`, `/quit` | Save history, exit |
| `/clear` | Reset conversation, new session |
| `/history` | List current messages |
| `/tokens` | Show total token count |
| `/tools` | List registered tools |
| `/sessions` | List saved conversations |
| `/resume [id]` | Resume a previous session |
| `/compact` | Manually trigger compaction |
| `/model [name]` | Switch model (aliases: `opus`, `sonnet`, `haiku`, etc.) |
| `/prompt` | Display current system prompt |
| `/plan` | Toggle plan mode (read-only + structured planning) |
| `/skills` | List available skills |
| `/help` | Show help text |
| `/<skill> [args]` | Invoke skill |

### System Prompt Assembly

```
[SYSTEM.md content]

[AGENTS.md content (if present)]

# Memory
[MEMORY.md content — read fresh from ~/.config/agent/MEMORY.md on every turn]

# Available Skills
- skill-name: Description for LLM discovery
- another-skill: Another description

# Plan Mode
[Read-only restriction text — only present when `/plan` is toggled on]
```

mem0 memories are *not* in the system prompt — the LLM retrieves them on demand via the `memory_search` tool. Plans produced by the `plan` tool are *not* re-injected either; the agent follows them from conversation history.

---

## Tool System

### Tool Protocol (`tools/base.py`)

```python
class Tool(Protocol):
    name: str                    # Unique identifier
    description: str             # For LLM (~1024 chars)
    input_schema: dict           # JSON Schema

    async def execute(self, **params) -> str
```

### Registry and Execution

- `ToolRegistry` — central dict mapping `name -> Tool`
  - `register(tool)`, `get(name)`, `unregister(name)`
  - `all_definitions()` — returns Anthropic API format list
  - `definitions_for(names)` — returns definitions filtered to a set of names
  - `clone_excluding(names)` — new registry with all tools except excluded (used by `SubagentTool`)
  - `clone_including(names)` — new registry with only specified tools (used by `PlanTool`)
  - `list_names()` — return tool names as a list
- `ToolExecutor(registry)` — lookup + execute pattern with error handling

### Built-in Tools

| Tool | Parameters | Description |
|------|-----------|-------------|
| `bash` | `command`, `timeout` | Async subprocess execution, captures stdout+stderr |
| `read` | `file_path`, `offset?`, `limit?` | Read file with line numbers, 2000-char line truncation |
| `write` | `file_path`, `content` | Create/overwrite file, creates parent dirs |
| `edit` | `file_path`, `old_string`, `new_string`, `replace_all?` | Find-and-replace (single match by default) |
| `glob` | `pattern`, `path?` | File pattern matching, max 100 results, sorted by mtime |
| `grep` | `pattern`, `path?`, `glob?`, `case_insensitive?`, `max_results?` | Content search via ripgrep or grep |
| `ask_user` | `question` | Prompt user for input during LLM execution |
| `web_fetch` | `url`, `prompt?`, `max_length?` | Fetch URL content (HTML/JSON/text), convert to text |
| `web_search` | `query`, `max_results?` | Web search via Brave Search API or DuckDuckGo |
| `subagent` | `action`, `task`, `system_prompt?`, `task_id?` | Delegate tasks to isolated sub-agents |
| `plan` | `task` | Create structured plan via read-only sub-agent |
| `memory_search` | `query`, `top_k?` | Search the agent's mem0 memory (scope per `memory.scope`) |
| `memory_save` | `content` | Append a curated entry to MEMORY.md |

Registration happens in `tools/builtin/__init__.py` via `register_builtins()`. `SubagentTool` and `PlanTool` are registered separately in `__main__.py` after builtins and MCP setup, since they need access to the full tool registry for cloning.

### MCP Tools (`tools/mcp/`)

- `MCPManager` connects to configured MCP servers via stdio or streamable HTTP transport
- On connection, discovers available tools from each server
- `MCPToolAdapter` wraps each MCP tool as an internal `Tool`:
  - Name: `mcp__<server>__<tool_name>`
  - Execution: delegates to `session.call_tool()`
  - Extracts text content from MCP result
- Environment variables in server config are interpolated at connection time
- Also supports `.agent/mcp.json` (Claude Code format) with `mcpServers` key, auto-converted to internal format

### Subagent System (`subagent/`, `tools/builtin/subagent.py`)

Enables the LLM to delegate tasks to isolated sub-agents that run their own LLM cycles.

**`SubagentRunner`** (`subagent/runner.py`)
- Runs an independent LLM cycle with an ephemeral conversation (no history persistence)
- Max 50 iterations hard limit
- Supports conversation compaction for long-running tasks
- Optional CLI streaming for real-time output
- Dynamic placeholder replacement in system prompts: `{{CWD}}`, `{{LOCAL_TIME}}`

**`SubagentTool`** (`tools/builtin/subagent.py`)
- Four actions:
  - `run` — synchronous execution, blocks until complete, returns result
  - `launch` — async execution, returns `task_id` immediately
  - `check` — check status of async task by `task_id`
  - `list` — list all async tasks and their statuses
- Tool filtering via `registry.clone_excluding()` — excludes `subagent` (prevent recursion), `plan`, `memory_save`, `ask_user`
- `SubagentManager` tracks async tasks with results

### Web Tools (`tools/builtin/web_fetch.py`, `tools/builtin/web_search.py`)

**`WebFetchTool`**
- HTTP GET via `httpx` with configurable timeout and User-Agent
- Supports HTML, plain text, JSON, XML, CSV content types
- HTML-to-text conversion: `html2text` library (preferred) with stdlib `HTMLParser` fallback
- Content truncation to `max_content_length` (default 50,000 chars)
- Optional `prompt` parameter prepended to content for context guidance

**`WebSearchTool`**
- **Brave Search API** (primary): requires `BRAVE_SEARCH_API_KEY` env var or `tools.web_search.api_key` config
- **DuckDuckGo Lite** (fallback): HTML parsing via custom `DDGParser`, no API key required
- Returns numbered results with title, URL, and snippet
- Configurable `max_results` (default 5, max 20)

---

## Memory System

### Two-Layer Design

| Layer | Purpose | Storage | Population |
|-------|---------|---------|------------|
| **MEMORY.md** | Stable, human-curated long-term knowledge — project conventions, user preferences, architecture decisions. | `~/.config/agent/MEMORY.md` (user-scoped, default; absolute / `~`-prefixed paths used as-is, relative paths join under `base_dir`) | Manual edits or via `memory_save` tool. Auto-loaded into every system prompt. |
| **mem0** | Automatic conversational memory — facts, decisions, context distilled from messages by an LLM. | Chroma vector store at `~/.config/agent/mem0/global/` (when `scope: global`, default) or `<project>/.agent/mem0/project/` (when `scope: project`). | Every user/assistant text message is auto-ingested. Searched on demand via `memory_search`. |

### Memory Manager (`memory/manager.py`)

Slim orchestrator — MEMORY.md I/O + delegate everything else to `Mem0Client`:

| Method | Description |
|--------|-------------|
| `load_context()` | Returns MEMORY.md content for the system prompt. |
| `save_main(content)` | Append to MEMORY.md. |
| `read_main()` | Full MEMORY.md content. |
| `search(query, top_k)` | Delegate to `Mem0Client.search`; `[]` if no client. |
| `handle_message_appended(message)` | Wired into `Conversation.on_append`; delegates to `Mem0Client.enqueue_message`. |

### Mem0 Client (`memory/mem0_client.py`)

Owns one `mem0.Memory` instance, one `user_id`, and a background ingestion worker.

```python
class Mem0Client:
    def __init__(self, config: Mem0Config, scope: str, project_dir: Path) -> None: ...

    def enqueue_message(self, message: Message) -> None
    async def search(self, query: str, top_k: int = 10) -> list[dict]
    async def aclose(self) -> None
```

**Scope mapping:**

| `scope` | `user_id` | Store dir |
|---|---|---|
| `"project"` | `str(project_dir.resolve())` | `config.project_store_dir` |
| `"global"`  | `"global"` | `config.global_store_dir` |

**Auto-ingestion path:**

```
Conversation.append(msg)
    -> on_append callback -> MemoryManager.handle_message_appended
    -> Mem0Client.enqueue_message
        - filter: skip non-user/assistant roles, non-text blocks, empty text
        - asyncio.Queue.put_nowait
        - lazy-start a background asyncio task on first call

Background worker:
    -> asyncio.Queue.get
    -> Mem0Client._ensure_init  (asyncio.to_thread on first call)
    -> mem0.Memory.add(messages, user_id=...)  (asyncio.to_thread)
```

`Conversation.append` never blocks on I/O. `load_messages` and `clear` deliberately skip the `on_append` callback (resuming a session must not re-ingest history).

### mem0 v2 API quirks

- `add(messages, *, user_id=..., agent_id=..., run_id=..., metadata=..., infer=...)` — `user_id` is a top-level kwarg.
- `search(query, *, top_k=20, filters=None, threshold=0.1, rerank=False, **kwargs)` — `user_id` must go inside `filters={'user_id': ...}`, and the param is `top_k` (not `limit`).
- `Mem0Client._search_kwargs` constructs the v2 shape; on `TypeError` it falls back to the legacy `user_id=`, `limit=` form.

### Logging

`Mem0Client` emits:
- `INFO` `mem0 ready: scope=…, user_id=…, store=…` once on first successful init.
- `INFO` `mem0 search (scope=…) query=… → N hit(s)` per search call.
- `WARNING` on init / ingest / search failure with a hint about `ANTHROPIC_API_KEY`, `OPENAI_API_KEY`, and `chromadb`.
- `DEBUG` `mem0 ingest [role]: <preview>` per ingested message.

The default level is `ERROR` (only failures surface). Set `AGENT_LOG_LEVEL=WARNING` for non-fatal mem0 problems, `=INFO` to add init confirmations and search hit counts, or `=DEBUG` for per-message ingest logs and full third-party output.

---

## Compaction System (`compaction/compactor.py`)

Prevents unbounded context growth by compressing old conversation messages. Note: there is no "extract facts to memory" phase — mem0 has already captured every conversation message in its index, so compaction only needs to free up tokens.

### Constructor

```python
Compactor(config: CompactionConfig, llm: LLMProvider, conversation: Conversation)
```

(`memory_manager` was removed — compaction no longer touches memory.)

### Trigger

Before each user message, checks if `conversation.total_tokens > threshold_tokens` (default 80,000).

### Two Phases

**Phase 1: Summarize Old Messages** (`_summarize_old_messages`)

1. Split messages: old (all but last N) + recent (last N, default 10)
2. Adjust the split point if it would orphan a `tool_result` from its `tool_use` pair
3. LLM call with summarization prompt:
   > Summarize: tasks performed, decisions and rationale, files modified, unresolved items
4. Replace old messages with a single summary user message prefixed `[Previous conversation summary]`
5. Recalculate `total_tokens`

**Phase 2: Truncate Oversized Tool Results** (`_truncate_all_tool_results`)

For every preserved message, replace any `tool_result` block whose content exceeds `_MAX_TOOL_RESULT_TOKENS` (800) with a ~3000-char preview suffixed `... [truncated from N tokens during compaction]`. This handles the case where a few messages contain huge tool dumps that no amount of summarization can shrink.

Summarization uses `_call_llm_simple()` — no tools, no extended thinking, max 2048 tokens. If the LLM fails, a placeholder summary is inserted so the conversation stays valid.

---

## Skills System

### SKILL.md Convention

Skills are markdown files with YAML frontmatter:

```markdown
---
name: review-pr
description: Reviews a pull request for bugs and style issues.
user-invocable: true
disable-model-invocation: false
argument-hint: "<pr-number>"
allowed-tools: Read, Grep, Bash
---

Review pull request $ARGUMENTS for:
- Bugs and logic errors
- Style violations
- Security issues

Current branch: !`git branch --show-current`
```

### Frontmatter Fields

| Field | Default | Description |
|-------|---------|-------------|
| `name` | (required) | Skill identifier, used as `/name` command |
| `description` | (required) | Brief text shown to LLM for discovery |
| `user-invocable` | `true` | Can be invoked via `/name` |
| `disable-model-invocation` | `false` | Hide from LLM (user-only) |
| `argument-hint` | `""` | Shown in `/help` |
| `allowed-tools` | all | Comma-separated tool names |

### Discovery Locations (first match wins)

1. Custom dirs: paths listed in `skills.dirs` config (e.g., `skills/`)
2. Project: `.agent/skills/<name>/SKILL.md`
3. Personal: `~/.config/agent/skills/<name>/SKILL.md`

### Rendering (`skill.py`)

On invocation (`/skill-name args`):

1. Load full SKILL.md body from disk (lazy — only metadata loaded at startup)
2. Argument substitution:
   - `$ARGUMENTS` -> all arguments
   - `$ARGUMENTS[N]` or `$N` -> positional argument
   - Fallback: append `ARGUMENTS: ...` if no placeholders found
3. Dynamic context resolution:
   - Pattern: `` !`command` ``
   - Executes shell command, inserts stdout (10s timeout)
4. Rendered body sent as user message to LLM

### LLM Awareness

Non-disabled skill metadata is injected into the system prompt so the LLM can suggest slash commands to users:

```
# Available Skills
- review-pr: Reviews a pull request for bugs and style issues.
- deploy: Deploys the application to staging.
```

---

## Plan Mode

Two complementary mechanisms support an explore-then-implement workflow:

1. **`/plan` command** — toggles plan mode on the main agent. While active, the system prompt includes a `# Plan Mode` block instructing the model to avoid edits and destructive commands and stick to read-only exploration. Run `/plan` again to exit.
2. **`plan` tool** — delegates to a read-only sub-agent that explores the codebase and writes a markdown plan to disk.

The two are independent and can be used together (toggle `/plan`, then call the `plan` tool from inside read-only mode) or separately.

### Plan Tool Architecture

- **Sub-agent**: `PlanTool` spawns a `SubagentRunner` with the `PLAN.md` system prompt and a read-only tool set; output is streamed to the CLI in real time
- **Session-bound**: Each plan is stored at `.agent/plans/<session_id>.md`, one plan per session
- **Conversation-driven**: The plan tool's output lands in the conversation history as a tool result. The agent follows the plan from history on subsequent turns — there is no system-prompt re-injection. `/resume` reloads the history, restoring the plan along with everything else
- **Disk artifact**: The plan file persists across sessions as a user-facing artifact, but the agent does not re-read it on every turn

### Plan File Format

Plans are free-form markdown — no fixed template, no required checkboxes:

```markdown
## Plan

1. Read the existing auth module
2. Add JWT verification middleware (create middleware function + token validation)
3. Write integration tests

### Critical Files for Implementation
- src/auth/middleware.py
- tests/test_auth.py
```

### Tool Filtering

```python
# PlanTool uses clone_including for read-only sub-agent
_PLAN_TOOLS = {"read", "glob", "grep", "bash", "web_fetch", "web_search", "ask_user"}
filtered = parent_registry.clone_including(allowed | mcp_tools)
```

---

## Conversation & History

### Conversation State (`core/conversation.py`)

```python
Conversation(
    messages: list[Message],
    system_prompt: str,
    total_tokens: int,
    on_append: Callable[[Message], None] | None = None,
)
```

- `append(message)` — adds message, updates token count, fires `on_append(message)` if set. Callback exceptions are swallowed at `DEBUG` so memory failures never crash the agent loop.
- `load_messages(messages)` — replaces the message list (used by `/resume`); **deliberately does not fire `on_append`** so resumed history isn't re-ingested.
- `clear()` — resets state; also skips `on_append`.
- `to_api_messages()` — converts to LLM API format.

`AgentLoop.__init__` sets `on_append=memory_manager.handle_message_appended` so every appended message — from user input, assistant streaming, and tool results — flows into the mem0 ingestion queue. Tool-related blocks are filtered inside `Mem0Client.enqueue_message` (only `role in {user, assistant}` AND text content survives).

### History Persistence (`history/storage.py`)

- Sessions saved as JSONL (append-only) to `.agent/history/`
- Filename: `<session_id>.jsonl` (session ID format: `YYYYMMDD_HHMMSS_randomhex`)
- Line 1: header with `session_id`, `timestamp`, `metadata` (model, provider)
- Subsequent lines: individual messages (`role`, `content`, `token_count`)
- Backward compatible: falls back to legacy `.json` format if `.jsonl` not found
- `list_sessions()` returns newest-first with message counts
- `find_session()` / `get_latest_session_id()` for session resume

mem0 ingestion is decoupled from history persistence — it happens at append time, not save time, so the conversation is searchable as soon as the message lands.

---

## CLI (`cli.py`)

Terminal interface built on Rich (rendering) and prompt_toolkit (input):

- `print_assistant_text()` / `print_text_delta()` — streamed output rendering
- `print_thinking_delta()` — extended thinking display
- `print_tool_use()` / `print_tool_result()` — tool execution feedback
- `print_compaction_notice()` — compaction status
- `print_usage()` — token usage after response
- `get_input()` — async multiline input (backslash `\` to continue)
- `print_welcome()` — startup banner

---

## Dependencies

### Required

| Package | Purpose |
|---------|---------|
| `anthropic>=0.45.0` | Anthropic Claude SDK |
| `rich>=13.0` | Terminal rendering |
| `prompt-toolkit>=3.0` | Input handling |
| `mcp>=1.0` | Model Context Protocol client |
| `httpx>=0.27` | HTTP client (web fetch/search tools) |
| `beautifulsoup4>=4.12` | HTML parsing (web tools) |
| `html2text>=2024.2` | HTML to markdown conversion (web tools) |
| `numpy>=2.0` | Vector math |
| `pyyaml>=6.0` | YAML parsing |
| `tiktoken>=0.8` | Token counting |
| `mem0ai>=0.1.0` | Persistent conversational memory (LLM-extracted) |
| `chromadb>=0.5` | Vector store backend used by mem0 |

### Runtime

- Python >= 3.13
- External: `rg` (ripgrep) preferred, falls back to `grep`
- Env vars:
  - `ANTHROPIC_API_KEY` — required (agent + mem0 fact extraction)
  - `OPENAI_API_KEY` — required when using the default `mem0.embedder.provider=openai`. Swap to Ollama / Voyage / etc. via `mem0.embedder` config to avoid it.
  - `AGENT_LOG_LEVEL` — optional, defaults to `ERROR`. Set to `WARNING` / `INFO` / `DEBUG` to surface progressively more detail.

---

## Key Design Decisions

1. **Protocol-based providers** — `LLMProvider` and `Tool` protocols allow swapping implementations without changing the core loop. Adding a new LLM provider or tool requires only implementing the protocol.

2. **No iteration limit** — the LLM cycle runs until the model produces a text-only response. This allows arbitrarily long tool-use chains for complex tasks.

3. **Two-layer memory** — MEMORY.md (curated, user-scoped, in the system prompt) handles facts the user wants pinned forever; mem0 (automatic, scoped per `memory.scope`, queried via `memory_search`) handles the rolling conversational record. The split keeps the system prompt small while making everything searchable.

4. **Auto-ingest via `Conversation.on_append`** — every appended message flows through a single hook, then through a background `asyncio.Queue` worker draining `mem0.Memory.add` via `asyncio.to_thread`. Zero effort for the model and zero added latency for the user. Filtering at enqueue keeps tool noise out.

5. **Single mem0 scope (`global` or `project`)** — one `Memory` instance, one `user_id`, one vector store. Half the LLM extraction cost vs. dual-write, and a clearer privacy story. Default `global` because cross-project recall is the common case for a personal assistant.

6. **Lazy skill loading** — only frontmatter is parsed at startup. Full skill bodies are loaded on invocation, keeping the initial system prompt small.

7. **Anthropic message format internally** — all messages use Anthropic's content block format, keeping the core loop clean and consistent.

8. **Graceful degradation** — `Mem0Client` init failure logs a warning (with a hint) and returns `False`; search yields `[]`, ingest is skipped, the agent keeps working. MCP connection failures don't block startup. Compaction LLM failures use placeholder summaries.

9. **Subagent isolation** — sub-agents run ephemeral conversations with filtered tool sets, preventing recursion and memory side effects. Max 50 iterations as a safety limit.

10. **Plan via conversation history** — the `plan` tool emits its plan as a tool result and persists a copy to disk. The agent follows the plan from conversation history on subsequent turns rather than re-injecting it into the system prompt every cycle. The `/plan` toggle is a complementary read-only restriction for the main agent during exploration.

11. **Adaptive thinking** — replaces fixed-budget extended thinking with adaptive mode (`low`/`medium`/`high` effort), letting the model decide how much reasoning to use.
