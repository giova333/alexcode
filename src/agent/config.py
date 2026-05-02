"""Configuration loading with YAML and environment variable interpolation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import json

import yaml


def _interpolate_env(value: str) -> str:
    """Replace ${VAR} patterns with environment variable values."""
    def replacer(match: re.Match) -> str:
        var_name = match.group(1)
        return os.environ.get(var_name, "")
    return re.sub(r"\$\{(\w+)}", replacer, value)


def _interpolate_recursive(obj: object) -> object:
    if isinstance(obj, str):
        return _interpolate_env(obj)
    if isinstance(obj, dict):
        return {k: _interpolate_recursive(v) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_interpolate_recursive(item) for item in obj]
    return obj


@dataclass
class AnthropicConfig:
    api_key: str = ""


@dataclass
class ReasoningConfig:
    enabled: bool = False
    effort: str = "high"       # low, medium, high, xhigh, max, auto (adaptive thinking)
    show_thinking: bool = False


@dataclass
class CompactionConfig:
    threshold_tokens: int = 80000
    keep_recent_messages: int = 10


@dataclass
class MemoryConfig:
    enabled: bool = True
    memory_file: str = "~/.config/agent/MEMORY.md"
    scope: str = "global"  # "global" (cross-project) or "project" (this project only)


@dataclass
class Mem0LLMConfig:
    provider: str = "anthropic"
    model: str = "claude-haiku-4-5"
    api_key: str = ""


@dataclass
class Mem0EmbedderConfig:
    provider: str = "openai"
    model: str = "text-embedding-3-small"
    api_key: str = ""


@dataclass
class Mem0Config:
    enabled: bool = True
    project_store_dir: str = ".agent/mem0/project/"
    global_store_dir: str = "~/.config/agent/mem0/global/"
    llm: Mem0LLMConfig = field(default_factory=Mem0LLMConfig)
    embedder: Mem0EmbedderConfig = field(default_factory=Mem0EmbedderConfig)


@dataclass
class HistoryConfig:
    dir: str = ".agent/history/"


@dataclass
class SkillsConfig:
    dirs: list[str] = field(default_factory=lambda: ["skills/"])


@dataclass
class WebFetchConfig:
    timeout: int = 30
    max_content_length: int = 50_000
    user_agent: str = "Mozilla/5.0 (compatible; AgentCLI/0.1)"


@dataclass
class WebSearchConfig:
    provider: str = "brave"
    api_key: str = ""
    max_results: int = 5


@dataclass
class ToolsConfig:
    bash_timeout: int = 120
    web_fetch: WebFetchConfig = field(default_factory=WebFetchConfig)
    web_search: WebSearchConfig = field(default_factory=WebSearchConfig)


@dataclass
class Config:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-6"
    max_tokens: int = 8192
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)

    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    mem0: Mem0Config = field(default_factory=Mem0Config)
    history: HistoryConfig = field(default_factory=HistoryConfig)
    skills: SkillsConfig = field(default_factory=SkillsConfig)
    tools: ToolsConfig = field(default_factory=ToolsConfig)
    mcp_servers: list[dict] = field(default_factory=list)

    @classmethod
    def load(cls, project_dir: Path | None = None) -> Config:
        """Load config by merging default -> project -> user configs."""
        merged: dict = {}

        # 1. Default config (bundled with package)
        default_path = Path(__file__).parent.parent.parent / "config.default.yaml"
        if default_path.exists():
            merged = _load_yaml(default_path)

        # 2. Project config
        if project_dir:
            project_cfg = project_dir / "config.yaml"
            if project_cfg.exists():
                _deep_merge(merged, _load_yaml(project_cfg))

        # 3. User config
        user_cfg = Path.home() / ".config" / "agent" / "config.yaml"
        if user_cfg.exists():
            _deep_merge(merged, _load_yaml(user_cfg))

        # 4. Load MCP servers from .agent/mcp.json (Claude Code format)
        #    mcp.json entries override YAML entries with the same name
        if project_dir:
            mcp_json_servers = _load_mcp_json(project_dir / ".agent" / "mcp.json")
            if mcp_json_servers:
                existing = merged.get("mcp_servers", []) or []
                json_names = {s["name"] for s in mcp_json_servers}
                # Keep YAML entries whose name is NOT in mcp.json
                deduped = [s for s in existing if s.get("name") not in json_names]
                deduped.extend(mcp_json_servers)
                merged["mcp_servers"] = deduped

        # 5. Interpolate env vars
        merged = _interpolate_recursive(merged)

        return _dict_to_config(merged)


def _load_mcp_json(path: Path) -> list[dict]:
    """Load MCP servers from a Claude Code-style mcp.json file.

    Converts the Claude Code format:
        {"mcpServers": {"name": {"type": "stdio", "command": "...", ...}}}
    to the internal list format:
        [{"name": "name", "transport": "stdio", "command": "...", ...}]
    """
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text())
    except (json.JSONDecodeError, OSError):
        return []

    mcp_servers = data.get("mcpServers", {})
    if not isinstance(mcp_servers, dict):
        return []

    result = []
    for name, server_config in mcp_servers.items():
        if not isinstance(server_config, dict):
            continue
        entry = {"name": name}
        # Map "type" to "transport" (Claude Code uses "type")
        entry["transport"] = server_config.get("type", server_config.get("transport", "stdio"))
        for key in ("command", "args", "env", "url", "headers"):
            if key in server_config:
                entry[key] = server_config[key]
        result.append(entry)
    return result


def _load_yaml(path: Path) -> dict:
    with open(path) as f:
        return yaml.safe_load(f) or {}


def _deep_merge(base: dict, override: dict) -> None:
    """Merge override into base in-place, recursing into dicts."""
    for key, value in override.items():
        if key in base and isinstance(base[key], dict) and isinstance(value, dict):
            _deep_merge(base[key], value)
        else:
            base[key] = value


def _build_mem0_config(data: dict) -> Mem0Config:
    """Build Mem0Config handling nested LLM/embedder sub-configs."""
    return Mem0Config(
        enabled=data.get("enabled", True),
        project_store_dir=data.get("project_store_dir", ".agent/mem0/project/"),
        global_store_dir=data.get("global_store_dir", "~/.config/agent/mem0/global/"),
        llm=Mem0LLMConfig(**data.get("llm", {})),
        embedder=Mem0EmbedderConfig(**data.get("embedder", {})),
    )


def _build_tools_config(data: dict) -> ToolsConfig:
    """Build ToolsConfig handling nested sub-configs."""
    return ToolsConfig(
        bash_timeout=data.get("bash_timeout", 120),
        web_fetch=WebFetchConfig(**data.get("web_fetch", {})),
        web_search=WebSearchConfig(**data.get("web_search", {})),
    )


def _dict_to_config(data: dict) -> Config:
    """Convert a raw dict into the typed Config dataclass tree."""
    anthropic_data = data.get("anthropic", {})
    anthropic_cfg = AnthropicConfig(api_key=anthropic_data.get("api_key", ""))

    return Config(
        provider=data.get("provider", "anthropic"),
        model=data.get("model", "claude-sonnet-4-20250514"),
        max_tokens=data.get("max_tokens", 8192),
        anthropic=anthropic_cfg,
        reasoning=ReasoningConfig(**data.get("reasoning", {})),
        compaction=CompactionConfig(**data.get("compaction", {})),
        memory=MemoryConfig(**data.get("memory", {})),
        mem0=_build_mem0_config(data.get("mem0", {})),
        history=HistoryConfig(**data.get("history", {})),
        skills=SkillsConfig(**data.get("skills", {})),
        tools=_build_tools_config(data.get("tools", {})),
        mcp_servers=data.get("mcp_servers", []) or [],
    )
