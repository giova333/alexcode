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

    # Tools
    tool_registry = ToolRegistry()
    register_builtins(tool_registry, config)
    tool_executor = ToolExecutor(tool_registry)

    # MCP servers
    mcp_manager = MCPManager(tool_registry)
    if config.mcp_servers:
        cli.print_info("Connecting to MCP servers...")
        connected = await mcp_manager.connect_all(config.mcp_servers)
        if connected:
            cli.print_info(f"Connected: {', '.join(connected)}")

    # Memory
    memory_manager = None
    if config.memory.enabled:
        memory_manager = MemoryManager(config.memory, project_dir)

    # History
    history = HistoryStorage(config.history.dir, project_dir)

    # Skills
    skill_loader = SkillLoader(config.skills.dirs, project_dir)
    skills = skill_loader.load_all()

    loop = AgentLoop(
        config=config,
        llm=llm,
        cli=cli,
        tool_registry=tool_registry,
        tool_executor=tool_executor,
        memory_manager=memory_manager,
        history=history,
        skill_loader=skill_loader,
        skills=skills,
    )

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
    args = parser.parse_args()

    try:
        asyncio.run(_async_main(args))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
