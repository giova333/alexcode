# AI Agent

![Alex Code](alex-code.png)

A CLI-based AI coding agent with tool use, memory, MCP support, and conversation compaction.

## Quick Start

```bash
# Install
pip install -e .

# API keys
export ANTHROPIC_API_KEY="sk-ant-..."   # main LLM + mem0 fact extraction
export OPENAI_API_KEY="sk-..."          # mem0 embedder (text-embedding-3-small)

# Run
python -m agent
```

## Requirements

- Python 3.13+
- An Anthropic API key (used for the agent and for mem0's memory extraction)
- An OpenAI API key (used for mem0's embedder; swap providers in `config.yaml` if you prefer Ollama / Voyage / etc.)

## Installation

```bash
cd /path/to/agent
pip install -e .
```

`mem0ai` and `chromadb` are bundled as required dependencies — no extras to install.

## Configuration

The agent reads config from three locations (merged in order):

1. `config.default.yaml` (bundled defaults)
2. `./config.yaml` (project-level overrides)
3. `~/.config/agent/config.yaml` (user-level overrides)

Environment variables are interpolated via `${VAR_NAME}` syntax.

### Minimal `config.yaml`

```yaml
model: claude-sonnet-4-6
```

## Usage

```bash
# Run
python -m agent

# Override model via CLI flag
python -m agent --model claude-sonnet-4-6

# Resume a previous session
python -m agent --resume [session-id]
```

Type your message and press **Enter** to send. Use `\` at the end of a line for multiline input.

### Commands

| Command | Description |
|---|---|
| `/help` | Show available commands |
| `/exit` | Save history and exit |
| `/clear` | Clear conversation and start a new session |
| `/history` | Show current conversation messages |
| `/tokens` | Show total token usage |
| `/tools` | List available tools |
| `/sessions` | List saved conversation sessions |
| `/resume [id]` | Resume a previous conversation session |
| `/compact` | Manually trigger conversation compaction |
| `/model [name]` | Switch LLM model (supports aliases: `opus`, `sonnet`, `haiku`) |
| `/prompt` | Display the current system prompt |
| `/plan` | Toggle plan mode on the main agent (read-only exploration) |
| `/skills` | List all available skills |
| `/<skill-name> [args]` | Invoke a skill (e.g., `/review-pr 123`) |

## Built-in Tools

The agent has access to these tools (called automatically by the LLM):

| Tool | Description |
|---|---|
| `bash` | Execute shell commands (configurable timeout) |
| `read` | Read file contents with line numbers |
| `write` | Create or overwrite files |
| `edit` | Find-and-replace text in files |
| `glob` | Find files by glob pattern |
| `grep` | Search file contents (uses ripgrep if available) |
| `ask_user` | Prompt the user for input during execution |
| `web_fetch` | Fetch and extract content from URLs (HTML, JSON, text) |
| `web_search` | Search the web (Brave Search API or DuckDuckGo fallback) |
| `subagent` | Delegate tasks to independent sub-agents (sync or async) |
| `plan` | Create structured implementation plans via read-only exploration |
| `memory_search` | Search the agent's mem0 memory across past sessions |
| `memory_save` | Append a curated entry to MEMORY.md (long-term knowledge) |

## Memory

The agent has two memory layers:

1. **MEMORY.md** — a single human-curated file at `~/.config/agent/MEMORY.md` (user-scoped, shared across all projects). Auto-loaded into every system prompt. Use it for stable, long-term knowledge: project conventions, user preferences, architecture decisions. The `memory_save` tool appends to it; you can also edit it directly.

2. **mem0** — automatic memory. Every user and assistant message is sent to a [mem0](https://mem0.ai) index in the background, where an LLM extracts and stores salient facts. The `memory_search` tool queries this index for recall across past sessions. Ingestion runs on an `asyncio` worker via `asyncio.to_thread`, so it never blocks the conversation.

### Scope

`memory.scope` in `config.yaml` selects where mem0 memories live:

| Scope | Store path | `user_id` | Use case |
|---|---|---|---|
| `global` (default) | `~/.config/agent/mem0/global/` | `"global"` | Personal CLI: your assistant remembers you across all projects. |
| `project` | `<project>/.agent/mem0/project/` | absolute project path | Team-shared repo: keep one project's conversations isolated. |

```yaml
memory:
  scope: global    # or "project"
```

### Stack defaults

- **LLM (memory extraction):** Anthropic `claude-haiku-4-5` (`${ANTHROPIC_API_KEY}`)
- **Embedder:** OpenAI `text-embedding-3-small` (`${OPENAI_API_KEY}`)
- **Vector store:** Chroma, file-backed — no extra service to run

All swappable in `config.yaml` under `mem0.llm`, `mem0.embedder`. See `config.default.yaml` for the full schema.

## Plan Mode

Two complementary mechanisms support an explore-then-implement workflow:

- **`/plan` command** — toggles plan mode on the main agent, restricting it to read-only exploration so it doesn't make changes while you're still planning. Run `/plan` again to exit.
- **`plan` tool** — delegates to a read-only sub-agent that explores the codebase and produces a markdown plan.

### How It Works

1. The LLM calls the `plan` tool with a task description (or you toggle `/plan` first to stay in read-only mode while planning)
2. The sub-agent explores using read-only tools (`read`, `glob`, `grep`, `bash`, `web_fetch`, `web_search`, `ask_user`)
3. It writes a markdown plan to `.agent/plans/<session_id>.md`
4. The tool's output is part of the conversation history, so the agent follows the plan from history on subsequent turns. Resuming the session via `/resume` reloads that history.

Plans are free-form markdown — no fixed template. Each session has its own plan file at `.agent/plans/<session_id>.md`, kept as a user-facing artifact.

## Conversation Compaction

When token usage exceeds the threshold (default: 80,000), the agent automatically:

1. Summarizes older messages, keeping the last N intact (`keep_recent_messages`, default 10)
2. Truncates oversized tool results (>800 tokens) in preserved messages so a single huge file dump can't dominate the context window

There is no separate "extract facts" step — mem0 has already captured every conversation message in its index, so compaction only needs to free up tokens.

Configure in `config.yaml`:

```yaml
compaction:
  threshold_tokens: 80000
  keep_recent_messages: 10
```

## Conversation History

All conversations are saved as JSONL (append-only) in `.agent/history/`. View past sessions with `/sessions`, or resume a previous session with `/resume [id]`.

## Logging

The agent logs at `ERROR` by default — only failures show. To see init confirmations, search hit counts, or debug mem0 issues, bump the level:

```bash
AGENT_LOG_LEVEL=WARNING python -m agent   # show non-fatal mem0 problems
AGENT_LOG_LEVEL=INFO    python -m agent   # also show "mem0 ready" and search hit counts
AGENT_LOG_LEVEL=DEBUG   python -m agent   # full firehose, including third-party internals
```

`Mem0Client` emits an `INFO` line on first successful init (with the active scope and store path) and a `WARNING` (with a configuration hint) on init / ingest / search failure. Chatty third-party loggers (`httpx`, `chromadb`, `mem0.*`, `openai`, `anthropic`, etc.) are tamped down unless you set `DEBUG`.

## MCP Servers

Connect to [Model Context Protocol](https://modelcontextprotocol.io/) servers to add external tools.

### Via `config.yaml`

```yaml
mcp_servers:
  - name: filesystem
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]

  - name: github
    transport: stdio
    command: npx
    args: ["-y", "@modelcontextprotocol/server-github"]
    env:
      GITHUB_TOKEN: "${GITHUB_TOKEN}"
```

### Via `.agent/mcp.json` (Claude Code format)

```json
{
  "mcpServers": {
    "filesystem": {
      "type": "stdio",
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/user/projects"]
    },
    "glean": {
      "type": "http",
      "url": "https://your-company.glean.com/mcp/default"
    }
  }
}
```

Supported transports: `stdio`, `http` (streamable HTTP). Both config formats are supported and merged (`.agent/mcp.json` takes precedence). MCP tools are registered on startup and appear as `mcp__<server>__<tool>` (e.g., `mcp__github__search_repositories`).

## Skills

Skills follow the [Anthropic Agent Skills](https://agentskills.io) convention. Each skill is a directory containing a `SKILL.md` file with YAML frontmatter.

### Discovery Locations

Skills are discovered from (higher precedence wins):
1. **Custom dirs:** paths listed in `skills.dirs` config (e.g., `skills/`)
2. **Project:** `.agent/skills/<name>/SKILL.md`
3. **Personal:** `~/.config/agent/skills/<name>/SKILL.md`

### Example: `.agent/skills/review-pr/SKILL.md`

```markdown
---
name: review-pr
description: Reviews a pull request for bugs, style issues, and best practices. Use when the user asks to review a PR.
argument-hint: "[pr-number]"
allowed-tools: Read, Grep, Glob
---

Review pull request #$ARGUMENTS.

PR diff:
!`gh pr diff $0`

Check for:
- Bugs and logic errors
- Security vulnerabilities
- Code style issues
- Missing error handling
```

### Frontmatter Fields

| Field | Default | Description |
|---|---|---|
| `name` | directory name | Becomes the `/slash-command` name |
| `description` | | Used by LLM to decide when to invoke (keep under 1024 chars) |
| `user-invocable` | `true` | Whether it appears as a `/command` |
| `disable-model-invocation` | `false` | Set `true` to prevent LLM from auto-invoking (e.g., `/deploy`) |
| `argument-hint` | | Shown in help (e.g., `[filename]`) |
| `allowed-tools` | | Comma-separated tool names |

### How It Works

- **Startup:** Only metadata (name + description) is loaded into the system prompt (~100 tokens per skill)
- **Invocation:** Type `/review-pr 123` to invoke. The full SKILL.md body is loaded, arguments substituted (`$ARGUMENTS`, `$0`, `$1`), and dynamic context (`!`command``) resolved
- **LLM auto-invoke:** Unless `disable-model-invocation: true`, the LLM can see skill metadata and decide to suggest invoking it
- **Supporting files:** Place templates, scripts, references alongside SKILL.md in the same directory

## Project Structure

```
src/agent/
├── __main__.py           # Entry point
├── cli.py                # Terminal I/O (rich + prompt_toolkit)
├── config.py             # YAML config loading
├── core/
│   ├── loop.py           # Main agent loop
│   ├── message.py        # Message dataclasses
│   ├── conversation.py   # Conversation state
│   └── tokens.py         # Token counting (tiktoken)
├── llm/
│   ├── base.py           # LLMProvider protocol
│   └── anthropic.py      # Anthropic Claude provider
├── tools/
│   ├── base.py           # Tool protocol
│   ├── registry.py       # Tool registry
│   ├── executor.py       # Tool dispatcher
│   ├── builtin/          # bash, read, write, edit, glob, grep, plan, subagent, web_fetch, web_search
│   └── mcp/              # MCP client + tool adapter
├── subagent/             # Sub-agent runner for isolated task delegation
├── skills/               # Skill loader
├── memory/               # manager.py, files.py (MEMORY.md), mem0_client.py
├── compaction/           # Token-based compaction (summarize + truncate)
└── history/              # JSONL conversation persistence

prompts/
├── SYSTEM.md             # Base system prompt
└── PLAN.md               # Plan mode system prompt
```
