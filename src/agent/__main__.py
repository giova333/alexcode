"""Entry point: python -m agent."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
from pathlib import Path

_LOG_LEVEL = os.environ.get("AGENT_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, _LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
# Quiet down chatty third-party loggers unless the user explicitly enabled DEBUG.
if _LOG_LEVEL != "DEBUG":
    for noisy in ("httpx", "httpcore", "chromadb", "urllib3", "openai", "anthropic"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    # mem0 emits per-message INFO/WARNING noise (chroma inserts, optional-spacy fallbacks).
    # Silence everything below ERROR; our own agent.memory.mem0_client logs cover the signal.
    for noisy in ("mem0", "mem0.utils.spacy_models", "mem0.vector_stores"):
        logging.getLogger(noisy).setLevel(logging.ERROR)

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
    from agent.llm.anthropic import AnthropicProvider
    return AnthropicProvider(config.anthropic, config.model)


async def _async_main(args: argparse.Namespace) -> None:
    project_dir = Path.cwd()
    config = Config.load(project_dir)

    # CLI overrides
    if args.model:
        config.model = args.model

    cli = CLI(working_dir=project_dir)
    llm = _create_llm_provider(config)

    # Memory (initialize early so tools can reference it)
    mem0_client = None
    if config.memory.enabled and config.mem0.enabled:
        try:
            from agent.memory.mem0_client import Mem0Client
            mem0_client = Mem0Client(
                config.mem0,
                scope=config.memory.scope,
                project_dir=project_dir,
            )
        except Exception as e:
            cli.print_info(f"mem0 disabled: {e}")

    memory_manager = None
    if config.memory.enabled:
        memory_manager = MemoryManager(
            config.memory,
            project_dir,
            mem0_client=mem0_client,
        )

    # Tools
    tool_registry = ToolRegistry()
    register_builtins(tool_registry, config, cli, memory_manager=memory_manager)
    tool_executor = ToolExecutor(tool_registry)

    # Subagent tool (registered after builtins so clone_excluding captures all tools)
    from agent.tools.builtin.subagent import SubagentTool
    from agent.core.loop import load_system_prompt

    subagent_tool = SubagentTool(
        llm=llm,
        parent_registry=tool_registry,
        config=config,
        default_system_prompt=load_system_prompt(),
        cli=cli,
    )
    tool_registry.register(subagent_tool)

    # MCP servers
    mcp_manager = MCPManager(tool_registry)
    if config.mcp_servers:
        cli.print_info("Connecting to MCP servers...")
        connected = await mcp_manager.connect_all(config.mcp_servers)
        if connected:
            cli.print_info(f"Connected: {', '.join(connected)}")

    # Plan tool (registered after MCP so it can see MCP tools in parent registry)
    from agent.tools.builtin.plan import PlanTool

    plan_tool = PlanTool(
        llm=llm,
        parent_registry=tool_registry,
        config=config,
        cli=cli,
    )
    tool_registry.register(plan_tool)

    # History
    history = HistoryStorage(config.history.dir, project_dir)

    # Skills
    skill_loader = SkillLoader(config.skills.dirs, project_dir)
    skills = skill_loader.load_all()

    # Register skills for autocompletion
    invocable = [(s.name, s.description or s.name) for s in skills if s.user_invocable]
    cli.set_skills(invocable)

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
        plan_tool=plan_tool,
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
        if mem0_client is not None:
            await mem0_client.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description="AI coding agent")
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
