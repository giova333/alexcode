"""Skill data model."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Skill:
    """A pluggable capability that injects instructions into the agent."""
    name: str
    description: str = ""
    instructions: str = ""
    trigger_patterns: list[str] = field(default_factory=list)
    tools: list[str] = field(default_factory=list)
    active: bool = False
