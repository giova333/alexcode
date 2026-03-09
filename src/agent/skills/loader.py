"""Discover and load skills from SKILL.md files following Anthropic convention.

Discovery locations (in precedence order):
  1. Personal:  ~/.config/agent/skills/<name>/SKILL.md
  2. Project:   .agent/skills/<name>/SKILL.md

Each skill directory contains a SKILL.md with YAML frontmatter + markdown body.
Only metadata (name + description) is loaded at startup (~100 tokens per skill).
The full body is loaded on-demand when the skill is invoked.
"""

from __future__ import annotations

from pathlib import Path

import yaml

from agent.skills.skill import Skill


class SkillLoader:
    """Discovers and loads skills from SKILL.md files."""

    def __init__(self, skill_dirs: list[str], base_dir: Path) -> None:
        self._dirs: list[Path] = []
        # Project-level skills
        for d in skill_dirs:
            self._dirs.append(base_dir / d)
        # Also check .agent/skills/ convention
        self._dirs.append(base_dir / ".agent" / "skills")
        # Personal skills
        self._dirs.append(Path.home() / ".config" / "agent" / "skills")

    def load_all(self) -> list[Skill]:
        """Discover all skills. Only reads frontmatter (metadata), not body."""
        seen_names: set[str] = set()
        skills: list[Skill] = []

        for skill_dir in self._dirs:
            if not skill_dir.exists():
                continue
            for entry in sorted(skill_dir.iterdir()):
                if not entry.is_dir():
                    continue
                skill_file = entry / "SKILL.md"
                if not skill_file.exists():
                    continue

                skill = self._load_metadata(skill_file, entry)
                if skill and skill.name not in seen_names:
                    seen_names.add(skill.name)
                    skills.append(skill)

        return skills

    def _load_metadata(self, skill_file: Path, skill_dir: Path) -> Skill | None:
        """Parse only the YAML frontmatter from a SKILL.md file."""
        try:
            content = skill_file.read_text()
        except OSError:
            return None

        frontmatter = _extract_frontmatter(content)
        if frontmatter is None:
            # No frontmatter — use directory name as skill name
            return Skill(name=skill_dir.name, skill_dir=skill_dir)

        try:
            data = yaml.safe_load(frontmatter)
        except yaml.YAMLError:
            return None

        if not isinstance(data, dict):
            return Skill(name=skill_dir.name, skill_dir=skill_dir)

        # Parse allowed-tools as comma-separated string -> list
        allowed_tools_raw = data.get("allowed-tools", "")
        if isinstance(allowed_tools_raw, str):
            allowed_tools = [t.strip() for t in allowed_tools_raw.split(",") if t.strip()]
        elif isinstance(allowed_tools_raw, list):
            allowed_tools = allowed_tools_raw
        else:
            allowed_tools = []

        return Skill(
            name=data.get("name", skill_dir.name),
            description=data.get("description", ""),
            user_invocable=data.get("user-invocable", True),
            disable_model_invocation=data.get("disable-model-invocation", False),
            argument_hint=data.get("argument-hint", ""),
            allowed_tools=allowed_tools,
            skill_dir=skill_dir,
        )

    def get_by_name(self, name: str, skills: list[Skill]) -> Skill | None:
        """Find a skill by name."""
        for skill in skills:
            if skill.name == name:
                return skill
        return None

    def get_invocable(self, skills: list[Skill]) -> list[Skill]:
        """Return skills that can be invoked via /slash-command."""
        return [s for s in skills if s.user_invocable]

    def get_model_available(self, skills: list[Skill]) -> list[Skill]:
        """Return skills whose metadata should be in the system prompt for the LLM."""
        return [s for s in skills if not s.disable_model_invocation]


def _extract_frontmatter(content: str) -> str | None:
    """Extract YAML frontmatter from a --- delimited block."""
    if not content.startswith("---"):
        return None
    end = content.find("---", 3)
    if end == -1:
        return None
    return content[3:end].strip()
