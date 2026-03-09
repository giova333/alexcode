"""Configuration loading with YAML and environment variable interpolation."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

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
class OAuthConfig:
    client_id: str = ""
    client_secret: str = ""
    token_url: str = ""
    scope: str = ""


@dataclass
class OpenAIConfig:
    auth: str = "api_key"
    api_key: str = ""
    base_url: str | None = None
    oauth: OAuthConfig = field(default_factory=OAuthConfig)


@dataclass
class ReasoningConfig:
    enabled: bool = False
    budget_tokens: int = 10000
    effort: str = "medium"  # low, medium, high (OpenAI o-series)
    show_thinking: bool = False


@dataclass
class CompactionConfig:
    threshold_tokens: int = 80000
    keep_recent_messages: int = 10


@dataclass
class MemoryConfig:
    enabled: bool = True
    memory_file: str = "MEMORY.md"
    daily_dir: str = "memory/daily/"
    context_days: int = 2          # days of daily notes to include in system prompt
    index_on_startup: bool = True  # index memory + recent history on startup


@dataclass
class EmbeddingConfig:
    enabled: bool = False
    model: str = "all-MiniLM-L6-v2"
    db_path: str = ".agent/embeddings.db"
    hybrid_alpha: float = 0.7
    chunk_size: int = 512
    chunk_overlap: int = 50


@dataclass
class HistoryConfig:
    dir: str = ".agent/history/"


@dataclass
class SkillsConfig:
    dirs: list[str] = field(default_factory=lambda: ["skills/"])


@dataclass
class ToolsConfig:
    bash_timeout: int = 120


@dataclass
class Config:
    provider: str = "anthropic"
    model: str = "claude-sonnet-4-20250514"
    max_tokens: int = 8192
    prompts_dir: str = "prompts/"
    anthropic: AnthropicConfig = field(default_factory=AnthropicConfig)
    openai: OpenAIConfig = field(default_factory=OpenAIConfig)
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)
    compaction: CompactionConfig = field(default_factory=CompactionConfig)
    memory: MemoryConfig = field(default_factory=MemoryConfig)
    embedding: EmbeddingConfig = field(default_factory=EmbeddingConfig)
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

        # 4. Interpolate env vars
        merged = _interpolate_recursive(merged)

        return _dict_to_config(merged)


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


def _dict_to_config(data: dict) -> Config:
    """Convert a raw dict into the typed Config dataclass tree."""
    oauth_data = data.get("openai", {}).get("oauth", {})
    oauth = OAuthConfig(
        client_id=oauth_data.get("client_id", ""),
        client_secret=oauth_data.get("client_secret", ""),
        token_url=oauth_data.get("token_url", ""),
        scope=oauth_data.get("scope", ""),
    )

    openai_data = data.get("openai", {})
    openai_cfg = OpenAIConfig(
        auth=openai_data.get("auth", "api_key"),
        api_key=openai_data.get("api_key", ""),
        base_url=openai_data.get("base_url"),
        oauth=oauth,
    )

    anthropic_data = data.get("anthropic", {})
    anthropic_cfg = AnthropicConfig(api_key=anthropic_data.get("api_key", ""))

    return Config(
        provider=data.get("provider", "anthropic"),
        model=data.get("model", "claude-sonnet-4-20250514"),
        max_tokens=data.get("max_tokens", 8192),
        prompts_dir=data.get("prompts_dir", "prompts/"),
        anthropic=anthropic_cfg,
        openai=openai_cfg,
        reasoning=ReasoningConfig(**data.get("reasoning", {})),
        compaction=CompactionConfig(**data.get("compaction", {})),
        memory=MemoryConfig(**data.get("memory", {})),
        embedding=EmbeddingConfig(**data.get("embedding", {})),
        history=HistoryConfig(**data.get("history", {})),
        skills=SkillsConfig(**data.get("skills", {})),
        tools=ToolsConfig(**data.get("tools", {})),
        mcp_servers=data.get("mcp_servers", []) or [],
    )
