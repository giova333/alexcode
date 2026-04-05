# AI Agent

A CLI-based AI coding agent with tool use, memory, MCP support, and conversation compaction.

## Quick Start

```bash
# Install
pip install -e .

# Set your API key
export ANTHROPIC_API_KEY="sk-ant-..."

# Run
python -m agent
```

## Requirements

- Python 3.13+
- An Anthropic API key

## Installation

```bash
cd /path/to/agent
pip install -e .

# Optional: install embedding support (adds ~400MB model on first use)
pip install -e ".[embedding]"
```

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
| `memory_search` | Hybrid semantic + keyword search across memory and history |
| `memory_save` | Save content to daily notes or main memory |
| `memory_read` | Read main memory, daily notes, or list available dates |

## Memory

When `memory.enabled: true` (default), the agent loads `MEMORY.md` into its system prompt. This lets you persist project context across sessions.

### File layout

```
.agent/memory/
├── MEMORY.md              # Main memory (loaded into every prompt)
└── daily/
    └── 2026-03-09.md      # Auto-generated daily notes
```

Create `MEMORY.md` manually or let the compaction system generate it.

## Plan Mode

The `plan` tool spawns a read-only sub-agent that explores the codebase and produces a structured implementation plan.

### How It Works

1. The LLM calls the `plan` tool with a task description
2. A sub-agent explores the codebase using read-only tools (`read`, `glob`, `grep`, `bash`, `web_fetch`, `web_search`)
3. It writes a structured plan as markdown checkboxes to `.agent/plans/<session_id>.md`
4. The plan is injected into the system prompt as an implementation guide
5. The LLM works through the plan, using `edit` to check off completed steps

### Plan Format

Plans are stored as markdown in `.agent/plans/<session_id>.md`:

```markdown
- [x] Read the existing auth module
- [ ] Add JWT verification middleware
  - [ ] Create middleware function
  - [ ] Add token validation
- [ ] Write integration tests
```

### Session Binding

Each plan is bound to its session. Different sessions can have independent plans. When you resume a session with `/resume`, its plan is automatically loaded. Plans persist across `/clear` and `/compact` within the same session.

## Conversation Compaction

When token usage exceeds the threshold (default: 80,000), the agent automatically:

1. Asks the LLM to extract key facts and decisions
2. Writes them to `MEMORY.md` and today's daily file
3. Summarizes older messages, keeping the last 10 intact
4. Truncates oversized tool results (>800 tokens) in preserved messages to prevent them from dominating the context window

Configure in `config.yaml`:

```yaml
compaction:
  threshold_tokens: 80000
  keep_recent_messages: 10
```

## Conversation History

All conversations are saved as JSONL (append-only) in `.agent/history/`. View past sessions with `/sessions`, or resume a previous session with `/resume [id]`.

## Embedding Search (Optional)

For semantic search over memory and history:

```bash
pip install -e ".[embedding]"
```

Enable in `config.yaml`:

```yaml
embedding:
  enabled: true
  model: all-MiniLM-L6-v2   # downloaded on first use
  hybrid_alpha: 0.7          # weight: 0=pure BM25, 1=pure semantic
```

Uses a hybrid of cosine similarity (sentence-transformers) and BM25 keyword search, stored in a local SQLite database.

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
├── memory/               # MEMORY.md, daily notes
├── embedding/            # SQLite store, indexer, hybrid search
├── compaction/           # Token-based compaction
└── history/              # JSONL conversation persistence

prompts/
├── SYSTEM.md             # Base system prompt
└── PLAN.md               # Plan mode system prompt
```
