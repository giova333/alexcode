"""Register all built-in tools."""

from __future__ import annotations

from agent.config import Config
from agent.tools.builtin.bash import BashTool
from agent.tools.builtin.edit import EditTool
from agent.tools.builtin.glob_tool import GlobTool
from agent.tools.builtin.grep import GrepTool
from agent.tools.builtin.read import ReadTool
from agent.tools.builtin.write import WriteTool
from agent.tools.registry import ToolRegistry


def register_builtins(registry: ToolRegistry, config: Config) -> None:
    registry.register(BashTool(timeout=config.tools.bash_timeout))
    registry.register(ReadTool())
    registry.register(WriteTool())
    registry.register(EditTool())
    registry.register(GlobTool())
    registry.register(GrepTool())
