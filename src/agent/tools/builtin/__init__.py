"""Register all built-in tools."""

from __future__ import annotations

from agent.cli import CLI
from agent.config import Config
from agent.memory.manager import MemoryManager
from agent.tools.builtin.ask_user import AskUserTool
from agent.tools.builtin.bash import BashTool
from agent.tools.builtin.edit import EditTool
from agent.tools.builtin.glob_tool import GlobTool
from agent.tools.builtin.grep import GrepTool
from agent.tools.builtin.read import ReadTool
from agent.tools.builtin.write import WriteTool
from agent.tools.registry import ToolRegistry


def register_builtins(
    registry: ToolRegistry,
    config: Config,
    cli: CLI,
    memory_manager: MemoryManager | None = None,
) -> None:
    registry.register(BashTool(timeout=config.tools.bash_timeout))
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
    registry.register(AskUserTool(cli))

    # Memory tools (only if memory is enabled)
    if memory_manager is not None:
        from agent.tools.builtin.memory_tool import (
            MemoryReadTool,
            MemorySaveTool,
            MemorySearchTool,
        )
        registry.register(MemorySearchTool(memory_manager))
        registry.register(MemorySaveTool(memory_manager))
        registry.register(MemoryReadTool(memory_manager))
