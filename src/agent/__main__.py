"""Entry point: python -m agent."""

from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from agent.cli import CLI
from agent.config import Config
from agent.core.loop import AgentLoop
from agent.history.storage import HistoryStorage
from agent.memory.manager import MemoryManager
from agent.skills.loader import SkillLoader
from agent.tools.builtin import register_builtins
from agent.tools.executor import ToolExecutor
from agent.tools.mcp.client import MCPManager
from agent.tools.registry import ToolRegistry


def _create_llm_provider(config: Config):
    """Instantiate the configured LLM provider."""
    if config.provider == "openai":
        from agent.llm.openai import OpenAIProvider
        return OpenAIProvider(config.openai, config.model)
    else:
        from agent.llm.anthropic import AnthropicProvider
        return AnthropicProvider(config.anthropic, config.model)


async def _async_main(args: argparse.Namespace) -> None:
    project_dir = Path.cwd()
    config = Config.load(project_dir)

    # CLI overrides
    if args.provider:
        config.provider = args.provider
    if args.model:
        config.model = args.model

    cli = CLI()
    llm = _create_llm_provider(config)

    # Memory (initialize early so tools can reference it)
    memory_manager = None
    if config.memory.enabled:
        memory_manager = MemoryManager(
            config.memory,
            project_dir,
            embedding_config=config.embedding if config.embedding.enabled else None,
            history_dir=config.history.dir,
        )

    # Tools
    tool_registry = ToolRegistry()
    register_builtins(tool_registry, config, cli, memory_manager=memory_manager)
    tool_executor = ToolExecutor(tool_registry)

    # MCP servers
    mcp_manager = MCPManager(tool_registry)
    if config.mcp_servers:
        cli.print_info("Connecting to MCP servers...")
        connected = await mcp_manager.connect_all(config.mcp_servers)
        if connected:
            cli.print_info(f"Connected: {', '.join(connected)}")

    # Index memory + recent history on startup
    if memory_manager and config.memory.index_on_startup:
        try:
            indexed = memory_manager.index_all()
            if indexed:
                cli.print_info(f"Indexed {indexed} memory chunks.")
        except Exception as e:
            cli.print_info(f"Memory indexing skipped: {e}")

    # History
    history = HistoryStorage(config.history.dir, project_dir)

    # Skills
    skill_loader = SkillLoader(config.skills.dirs, project_dir)
    skills = skill_loader.load_all()

    loop = AgentLoop(
        config=config,
        llm=llm,
        cli=cli,
        project_dir=project_dir,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        memory_manager=memory_manager,
        history=history,
        skill_loader=skill_loader,
        skills=skills,
    )

    # Resume a previous session if requested
    if args.resume:
        if args.resume == "__latest__":
            session_id = history.get_latest_session_id()
        else:
            session_id = history.find_session(args.resume)
        if session_id and loop.resume_session(session_id):
            msg_count = len(loop._conversation.messages)
            cli.print_info(f"Resumed session: {session_id} ({msg_count} messages)")
        else:
            cli.print_error(f"Session not found: {args.resume}" if args.resume != "__latest__" else "No previous sessions.")

    try:
        await loop.run()
    except (KeyboardInterrupt, SystemExit):
        cli.print_info("Goodbye!")
    finally:
        await mcp_manager.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI coding agent")
    parser.add_argument("--provider", choices=["anthropic", "openai"], default=None)
    parser.add_argument("--model", default=None)
    parser.add_argument("--resume", nargs="?", const="__latest__", default=None,
                        help="Resume a previous session (optionally provide session ID or prefix)")
    args = parser.parse_args()

    try:
        asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
