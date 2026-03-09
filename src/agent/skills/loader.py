"""Discover and load skill definitions from YAML files."""

from __future__ import annotations

import re
from pathlib import Path

import yaml

from agent.skills.skill import Skill


class SkillLoader:
    """Loads skills from YAML files in configured directories."""

    def __init__(self, skill_dirs: list[str], base_dir: Path) -> None:
        self._dirs = [base_dir / d for d in skill_dirs]

    def load_all(self) -> list[Skill]:
        """Load all skill definitions from all configured directories."""
        skills = []
        for skill_dir in self._dirs:
            if not skill_dir.exists():
                continue
            for path in skill_dir.glob("*.yaml"):
                skill = self._load_skill(path)
                if skill:
                    skills.append(skill)
            for path in skill_dir.glob("*.yml"):
                skill = self._load_skill(path)
                if skill:
                    skills.append(skill)
        return skills

    def _load_skill(self, path: Path) -> Skill | None:
        try:
            with open(path) as f:
                data = yaml.safe_load(f)
            if not data or not isinstance(data, dict):
                return None
            return Skill(
                name=data.get("name", path.stem),
                description=data.get("description", ""),
                instructions=data.get("instructions", ""),
                trigger_patterns=data.get("trigger_patterns", []),
                tools=data.get("tools", []),
            )
        except Exception:
            return None

    def match_skills(self, user_message: str, skills: list[Skill]) -> list[Skill]:
        """Return skills whose trigger_patterns match the user message."""
        matched = []
        for skill in skills:
            if skill.active:
                continue
            for pattern in skill.trigger_patterns:
                try:
                    if re.search(pattern, user_message):
                        matched.append(skill)
                        break
                except re.error:
                    continue
        return matched
