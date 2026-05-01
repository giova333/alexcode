"""Integration tests for configuration loading and merging."""

from __future__ import annotations

import os
from pathlib import Path

import pytest
import yaml

from agent.config import Config, _interpolate_env, _deep_merge, _dict_to_config


@pytest.mark.integration
class TestConfigLoading:
    """Config loading from YAML files."""

    def test_load_produces_valid_config(self):
        """Config.load() with no project dir still produces a valid Config."""
        config = Config.load()
        assert isinstance(config, Config)
        assert config.provider == "anthropic"
        assert config.max_tokens > 0
        assert config.model != ""

    def test_project_config_overrides(self, tmp_path: Path):
        """Project config.yaml values are merged into the final config."""
        project_cfg = tmp_path / "config.yaml"
        project_cfg.write_text(yaml.dump({"model": "custom-model-override"}))

        config = Config.load(tmp_path)
        assert config.model == "custom-model-override"


@pytest.mark.integration
class TestEnvInterpolation:

    def test_interpolate_env_var(self, monkeypatch):
        monkeypatch.setenv("TEST_API_KEY", "sk-secret-123")
        result = _interpolate_env("${TEST_API_KEY}")
        assert result == "sk-secret-123"

    def test_interpolate_missing_var(self):
        result = _interpolate_env("${DEFINITELY_NOT_SET_XYZ}")
        assert result == ""

    def test_interpolate_mixed(self, monkeypatch):
        monkeypatch.setenv("MY_HOST", "localhost")
        result = _interpolate_env("http://${MY_HOST}:8080")
        assert result == "http://localhost:8080"

    def test_no_interpolation_needed(self):
        result = _interpolate_env("plain string")
        assert result == "plain string"


@pytest.mark.integration
class TestDeepMerge:

    def test_flat_merge(self):
        base = {"a": 1, "b": 2}
        override = {"b": 3, "c": 4}
        _deep_merge(base, override)
        assert base == {"a": 1, "b": 3, "c": 4}

    def test_nested_merge(self):
        base = {"outer": {"a": 1, "b": 2}}
        override = {"outer": {"b": 3, "c": 4}}
        _deep_merge(base, override)
        assert base == {"outer": {"a": 1, "b": 3, "c": 4}}

    def test_override_replaces_non_dict(self):
        base = {"key": "string_value"}
        override = {"key": {"nested": True}}
        _deep_merge(base, override)
        assert base == {"key": {"nested": True}}


@pytest.mark.integration
class TestDictToConfig:

    def test_minimal_config(self):
        config = _dict_to_config({})
        assert config.provider == "anthropic"
        assert config.max_tokens == 8192

    def test_full_config(self):
        data = {
            "provider": "anthropic",
            "model": "claude-opus-4-6",
            "max_tokens": 4096,
            "anthropic": {"api_key": "test"},
            "reasoning": {"enabled": True, "effort": "medium"},
            "compaction": {"threshold_tokens": 50000},
            "memory": {"enabled": False, "scope": "project"},
            "mem0": {
                "enabled": True,
                "project_store_dir": ".agent/mem0/proj/",
                "llm": {"provider": "anthropic", "model": "claude-haiku-4-5", "api_key": "k"},
                "embedder": {"provider": "openai", "model": "text-embedding-3-small", "api_key": "e"},
            },
        }
        config = _dict_to_config(data)
        assert config.model == "claude-opus-4-6"
        assert config.max_tokens == 4096
        assert config.anthropic.api_key == "test"
        assert config.reasoning.enabled is True
        assert config.reasoning.effort == "medium"
        assert config.compaction.threshold_tokens == 50000
        assert config.memory.enabled is False
        assert config.memory.scope == "project"
        assert config.mem0.enabled is True
        assert config.mem0.project_store_dir == ".agent/mem0/proj/"
        assert config.mem0.llm.model == "claude-haiku-4-5"
        assert config.mem0.embedder.api_key == "e"


@pytest.mark.integration
class TestMCPJsonLoading:
    """Loading MCP servers from .agent/mcp.json."""

    def test_mcp_json_loaded(self, tmp_path: Path):
        import json
        mcp_dir = tmp_path / ".agent"
        mcp_dir.mkdir(parents=True)
        mcp_json = mcp_dir / "mcp.json"
        mcp_json.write_text(json.dumps({
            "mcpServers": {
                "my-server": {
                    "type": "stdio",
                    "command": "my-server-bin",
                    "args": ["--port", "8080"],
                }
            }
        }))

        # Create minimal default config
        (tmp_path / "config.default.yaml").write_text(yaml.dump({"provider": "anthropic"}))

        config = Config.load(tmp_path)
        assert len(config.mcp_servers) == 1
        assert config.mcp_servers[0]["name"] == "my-server"
        assert config.mcp_servers[0]["transport"] == "stdio"
