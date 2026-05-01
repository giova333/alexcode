"""Shared fixtures for the test suite."""

from __future__ import annotations

import pytest
from pathlib import Path

from agent.config import (
    AnthropicConfig,
    CompactionConfig,
    Config,
    HistoryConfig,
    Mem0Config,
    MemoryConfig,
    ReasoningConfig,
    SkillsConfig,
    ToolsConfig,
)


@pytest.fixture
def project_root() -> Path:
    return Path(__file__).parent.parent


@pytest.fixture
def test_config(tmp_path: Path) -> Config:
    """A Config wired to tmp_path so tests never touch real project files."""
    return Config(
        provider="anthropic",
        model="test-model",
        max_tokens=1024,
        anthropic=AnthropicConfig(api_key="test-key"),
        reasoning=ReasoningConfig(enabled=False),
        compaction=CompactionConfig(threshold_tokens=500, keep_recent_messages=4),
        memory=MemoryConfig(
            enabled=True,
            memory_file=".agent/memory/MEMORY.md",
            scope="project",
        ),
        mem0=Mem0Config(enabled=False),
        history=HistoryConfig(dir=".agent/history/"),
        skills=SkillsConfig(dirs=[]),
        tools=ToolsConfig(bash_timeout=10),
    )
