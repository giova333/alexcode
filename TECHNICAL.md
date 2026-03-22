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
    |         +---> Compactor: flush facts to memory + summarize old messages
    |
    +---> Build system prompt (SYSTEM.md + AGENTS.md + memory context + skill metadata + active plan)
    |
    +---> Stream LLM response (Anthropic)
    |         |
    |         +---> TextDelta ---> Print to terminal
    |         +---> ThinkingDelta ---> Print if enabled
    |         +---> ToolUseEvent ---> Execute tool ---> Append result ---> Loop back
    |         +---> ResponseComplete ---> Usage info
    |
    +---> Save history + index for search
```

### Initialization Flow (`__main__.py`)

1. Parse CLI args (`--model`, `--resume`)
2. Load config: `config.default.yaml` -> project `config.yaml` -> user `~/.config/agent/config.yaml`
3. Override with CLI args
4. Create LLM provider (Anthropic)
5. Initialize CLI (Rich console + prompt_toolkit)
6. Create `MemoryManager` (if enabled)
7. Create `ToolRegistry` + register built-in tools
8. Connect MCP servers + register MCP tools
9. Index memory + history (if `index_on_startup: true`)
10. Discover skills
11. Create `AgentLoop` with all components
12. Resume session if `--resume` flag provided
13. Run loop

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
        registry.py         # Dict-based tool registry
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
            memory_tool.py  # Memory search/save/read tools
            update_plan.py  # Plan mode: update session plan
        mcp/
            adapter.py      # Wraps MCP tool as internal Tool
            client.py       # MCP server connection manager (stdio)
    memory/
        manager.py          # Memory orchestrator (load, save, search, index)
        files.py            # MEMORY.md file I/O
        daily.py            # Daily notes (memory/daily/YYYY-MM-DD.md)
    embedding/
        indexer.py          # Text chunking + embedding generation
        store.py            # SQLite storage for embeddings + content hashes
        search.py           # Hybrid semantic + BM25 search
    skills/
        skill.py            # Skill data model, rendering, arg substitution
        loader.py           # Skill discovery + YAML frontmatter parsing
    compaction/
        compactor.py        # Conversation compression (extract + summarize)
    history/
        storage.py          # JSON conversation persistence

prompts/
    SYSTEM.md               # Base system prompt

.agent/
    mcp.json                # MCP server config (Claude Code format)
    plans/                  # Session plan files (<session_id>.json)
    memory/
        MEMORY.md           # Main long-term knowledge
        daily/              # Daily notes (YYYY-MM-DD.md)

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
        budget_tokens: int = 10000      # min 1024
        show_thinking: bool = True
    compaction: CompactionConfig
        threshold_tokens: int = 80000
        keep_recent_messages: int = 10
    memory: MemoryConfig
        enabled: bool = True
        memory_file: str = ".agent/memory/MEMORY.md"
        daily_dir: str = ".agent/memory/daily/"
        context_days: int = 2
        index_on_startup: bool = True
    embedding: EmbeddingConfig
        enabled: bool = True
        model: str = "all-MiniLM-L6-v2"
        db_path: str = ".agent/embeddings.db"
        hybrid_alpha: float = 0.7      # 0=BM25, 1=semantic
        chunk_size: int = 512           # words per chunk
        chunk_overlap: int = 50         # word overlap
    history: HistoryConfig
        dir: str = ".agent/history/"
    skills: SkillsConfig
        dirs: list[str] = ["skills/"]
    tools: ToolsConfig
        bash_timeout: int = 120
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
  budget_tokens: 10000
  show_thinking: true

compaction:
  threshold_tokens: 80000
  keep_recent_messages: 10

memory:
  enabled: true
  memory_file: .agent/memory/MEMORY.md
  daily_dir: .agent/memory/daily/
  context_days: 2
  index_on_startup: true

embedding:
  enabled: true
  model: all-MiniLM-L6-v2
  db_path: .agent/embeddings.db
  hybrid_alpha: 0.7
  chunk_size: 512
  chunk_overlap: 50

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
- Extended thinking: sends `thinking.type = "enabled"` with `budget_tokens` (min 1024). If `max_tokens <= budget`, auto-adjusts to `budget + max_tokens`

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

1. Build system prompt: `SYSTEM.md` + `AGENTS.md` + memory context + skill metadata + active plan
2. Get tool definitions from registry (filtered in plan mode)
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
[MEMORY.md content]

## Notes — 2026-03-09
[Today's daily notes]

## Notes — 2026-03-08
[Yesterday's daily notes]

# Available Skills
- skill-name: Description for LLM discovery
- another-skill: Another description

# Plan Mode (ACTIVE) / Active Plan
[Plan JSON with instructions — only if plan mode or incomplete plan exists]
```

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
  - `definitions_for(names)` — returns definitions filtered to a set of names (used by plan mode)
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
| `memory_search` | `query`, `top_k?` | Hybrid search across memory + history |
| `memory_save` | `content`, `target?` | Save to `daily` (default) or `main` memory |
| `memory_read` | `target`, `date?` | Read `main`, `daily`, or list `dates` |
| `update_plan` | `explanation`, `plan` | Update session plan (array of `{step, status}`) |

Registration happens in `tools/builtin/__init__.py`. `register_builtins()` returns the `UpdatePlanTool` instance so the agent loop can wire it to the session's plan file.

### MCP Tools (`tools/mcp/`)

- `MCPManager` connects to configured MCP servers via stdio or streamable HTTP transport
- On connection, discovers available tools from each server
- `MCPToolAdapter` wraps each MCP tool as an internal `Tool`:
  - Name: `mcp__<server>__<tool_name>`
  - Execution: delegates to `session.call_tool()`
  - Extracts text content from MCP result
- Environment variables in server config are interpolated at connection time
- Also supports `.agent/mcp.json` (Claude Code format) with `mcpServers` key, auto-converted to internal format

---

## Memory System

### Two-Tier Design

```
.agent/memory/
    MEMORY.md               # Stable, long-term knowledge
    daily/
        2026-03-09.md       # Temporal, session-level notes
        2026-03-08.md
```

**MEMORY.md** — project conventions, user preferences, architecture decisions. Rarely changes. Loaded in full into every system prompt.

**Daily notes** — session discoveries, decisions, activity logs. Auto-timestamped (`## HH:MM:SS`). Last N days (default 2) loaded into system prompt.

### Memory Manager (`memory/manager.py`)

Central orchestrator for all memory operations:

| Method | Description |
|--------|-------------|
| `load_context()` | MEMORY.md + last N days -> system prompt |
| `save_main(content)` | Append to MEMORY.md, re-index |
| `save_daily(content)` | Append to today's daily, re-index |
| `read_main()` | Full MEMORY.md content |
| `read_daily(date?)` | Specific date or today |
| `list_daily_dates()` | Available daily files |
| `search(query, top_k)` | Hybrid search or keyword fallback |
| `index_all()` | Index memory + recent history (startup) |
| `index_session(text, id)` | Index after session save |

### Indexing Strategy

On startup (`index_all`):
- Index MEMORY.md
- Index last 7 days of daily notes
- Index last 2 days of conversation history JSON files

On save: re-index the changed file immediately.

After session: index the new conversation.

Content-hash deduplication prevents re-indexing unchanged sources.

---

## Embedding Search

### Pipeline

```
Source text
    |
    v
Chunking (word-based, configurable size + overlap)
    |
    v
sentence-transformers model (all-MiniLM-L6-v2)
    |
    v
SQLite store (chunks table + source_hashes table)
```

### Components

**`EmbeddingIndexer`** (`embedding/indexer.py`)
- Chunks text by word count (default 512 words, 50 word overlap)
- Generates embeddings via sentence-transformers
- Content-hash dedup: skips sources with unchanged hash
- Methods: `index_text()`, `index_file()`, `index_directory()`

**`EmbeddingStore`** (`embedding/store.py`)
- SQLite database at `.agent/embeddings.db`
- `chunks` table: `id`, `source`, `chunk_text`, `embedding` (blob), `updated_at`
- `source_hashes` table: tracks content hashes to skip re-indexing
- Methods: `insert()`, `insert_batch()`, `get_all()`, `delete_by_source()`

**`HybridSearch`** (`embedding/search.py`)
- Semantic: cosine similarity between query embedding and stored embeddings
- Keyword: BM25 ranking via `rank_bm25`
- Combination: `score = alpha * semantic + (1 - alpha) * bm25`
- Default `hybrid_alpha = 0.7` (70% semantic, 30% BM25)
- Scores normalized to [0, 1]
- Falls back to keyword-only search if embeddings are unavailable

---

## Compaction System (`compaction/compactor.py`)

Prevents unbounded context growth by compressing old conversation messages.

### Trigger

Before each user message, checks if `conversation.total_tokens > threshold_tokens` (default 80,000).

### Two-Phase Process

**Phase 1: Flush to Memory** (`_flush_to_memory`)

1. Format entire conversation as readable text
2. LLM call with extraction prompt:
   > Extract key facts: decisions made, project facts, user preferences, problems solved, file paths and patterns
3. Save extracted facts to today's daily notes
4. Automatic re-indexing

**Phase 2: Summarize Old Messages** (`_summarize_old_messages`)

1. Split messages: old (all but last N) + recent (last N, default 10)
2. LLM call with summarization prompt:
   > Summarize: tasks performed, decisions and rationale, files modified, unresolved items
3. Replace old messages with a single summary message
4. Truncate oversized tool results in recent messages (>800 tokens → ~3000 char preview)
5. Recalculate `total_tokens`
6. Recent messages preserved intact

The tool result truncation (step 4) prevents large tool responses (e.g., Glean searches, file reads at 30k+ tokens each) from consuming the entire post-compaction context window. The assistant's text responses — which already contain the processed/summarized findings — remain untouched.

Both LLM calls use `_call_llm_simple()` — no tools, no extended thinking, max 2048 tokens. Failures are handled gracefully: if extraction fails, only summarization runs; if summarization fails, a placeholder is inserted.

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

Plan mode restricts the LLM to read-only tools and a structured `update_plan` tool, enabling an explore-then-implement workflow.

### Architecture

- **Session-bound**: Each plan is stored at `.agent/plans/<session_id>.json`, one plan per session
- **Persistent**: The plan file on disk is the source of truth. `_build_system_prompt()` reads it fresh on every LLM call, so it survives compaction (which replaces conversation messages) and `/clear` (which resets conversation state)
- **Auto-loaded**: When resuming a session via `/resume`, `_load_session_plan()` checks if an incomplete plan exists for that session and wires it up

### Plan File Format

```json
{
  "explanation": "High-level approach description",
  "plan": [
    { "step": "Step description", "status": "pending|in_progress|completed" }
  ]
}
```

### Two Modes of Plan Injection

1. **In plan mode** (`_plan_mode = True`): System prompt includes planning instructions (read-only constraints, workflow guidance). Tool definitions filtered to `PLAN_MODE_TOOLS = {read, glob, grep, ask_user, memory_search, memory_read, update_plan}` plus any `mcp__*` tools. Safety net in `_execute_tool()` rejects blocked tools.

2. **After plan mode** (plan file exists with incomplete steps): System prompt includes the plan as an implementation guide. All tools are available. The LLM uses `update_plan` to mark steps as `in_progress`/`completed` as it works.

### `/plan` Command Flow

- **Enter**: Creates `.agent/plans/<session_id>.json` (or reuses existing). Sets `_plan_mode = True`, changes CLI prompt to `[plan] >>> `, wires `UpdatePlanTool._plan_file`.
- **Exit**: Sets `_plan_mode = False`, reverts prompt. Plan file and tool wiring are preserved for implementation phase.
- **Re-enter**: Reopens the same session plan file — the LLM can rewrite it with a different plan.

### Tool Filtering (`_get_tool_definitions`)

```python
if self._plan_mode:
    allowed = {n for n in all_names if n in PLAN_MODE_TOOLS or n.startswith("mcp__")}
    return self._tool_registry.definitions_for(allowed)
```

---

## Conversation & History

### Conversation State (`core/conversation.py`)

```python
Conversation(
    messages: list[Message],
    system_prompt: str,
    total_tokens: int,
)
```

- `append(message)` — adds message, updates token count
- `to_api_messages()` — converts to LLM API format
- `clear()` — resets state

### History Persistence (`history/storage.py`)

- Sessions saved as JSONL (append-only) to `.agent/history/`
- Filename: `<session_id>.jsonl` (session ID format: `YYYYMMDD_HHMMSS_randomhex`)
- Line 1: header with `session_id`, `timestamp`, `metadata` (model, provider)
- Subsequent lines: individual messages (`role`, `content`, `token_count`)
- Backward compatible: falls back to legacy `.json` format if `.jsonl` not found
- `list_sessions()` returns newest-first with message counts
- `find_session()` / `get_latest_session_id()` for session resume
- After save, conversation text is indexed for embedding search

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
| `numpy>=2.0` | Vector math for similarity |
| `pyyaml>=6.0` | YAML parsing |
| `tiktoken>=0.8` | Token counting |

### Optional (embedding extra)

| Package | Purpose |
|---------|---------|
| `sentence-transformers>=3.0` | Embedding generation (~400MB model) |
| `rank-bm25>=0.2` | BM25 keyword ranking |

Install: `pip install ai-agent[embedding]`

### Runtime

- Python >= 3.13
- External: `rg` (ripgrep) preferred, falls back to `grep`

---

## Key Design Decisions

1. **Protocol-based providers** — `LLMProvider` and `Tool` protocols allow swapping implementations without changing the core loop. Adding a new LLM provider or tool requires only implementing the protocol.

2. **No iteration limit** — the LLM cycle runs until the model produces a text-only response. This allows arbitrarily long tool-use chains for complex tasks.

3. **Two-tier memory** — separating stable knowledge (MEMORY.md) from temporal notes (daily/) prevents context pollution and keeps the system prompt focused.

4. **Hybrid search** — combining semantic and BM25 search provides both conceptual and keyword matching. The 70/30 default blend favors semantic understanding while maintaining exact-match capability.

5. **Content-hash dedup** — embedding indexing tracks source content hashes to skip re-processing unchanged files, keeping startup fast.

6. **Lazy skill loading** — only frontmatter is parsed at startup. Full skill bodies are loaded on invocation, keeping the initial system prompt small.

7. **Anthropic message format internally** — all messages use Anthropic's content block format, keeping the core loop clean and consistent.

8. **Graceful degradation** — embedding search falls back to keyword search if sentence-transformers is unavailable. MCP connection failures don't block startup. Compaction LLM failures use placeholder summaries.
