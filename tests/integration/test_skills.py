"""Integration tests for the skills system: discovery, loading, rendering, invocation."""

from __future__ import annotations

from pathlib import Path

import pytest

from agent.skills.loader import SkillLoader, _extract_frontmatter
from agent.skills.skill import Skill, _extract_body, _resolve_dynamic_context

from tests.integration.conftest import build_agent


# ---------------------------------------------------------------------------
# Skill file creation helper
# ---------------------------------------------------------------------------

def _create_skill(
    base_dir: Path,
    name: str,
    description: str = "A test skill",
    body: str = "Do the thing with $ARGUMENTS",
    user_invocable: bool = True,
    disable_model_invocation: bool = False,
) -> Path:
    """Create a SKILL.md file in the expected directory structure."""
    skill_dir = base_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    skill_file = skill_dir / "SKILL.md"
    skill_file.write_text(
        f"---\n"
        f"name: {name}\n"
        f"description: {description}\n"
        f"user-invocable: {str(user_invocable).lower()}\n"
        f"disable-model-invocation: {str(disable_model_invocation).lower()}\n"
        f"---\n\n"
        f"{body}\n"
    )
    return skill_dir


# ---------------------------------------------------------------------------
# Frontmatter / body extraction
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestFrontmatterExtraction:

    def test_extract_frontmatter(self):
        content = "---\nname: test\ndescription: foo\n---\nBody here"
        fm = _extract_frontmatter(content)
        assert fm is not None
        assert "name: test" in fm

    def test_no_frontmatter(self):
        assert _extract_frontmatter("Just body text") is None

    def test_missing_closing_delimiter(self):
        assert _extract_frontmatter("---\nname: test\nno closing") is None


@pytest.mark.integration
class TestBodyExtraction:

    def test_extract_body(self):
        content = "---\nname: test\n---\nThe actual instructions"
        body = _extract_body(content)
        assert body == "The actual instructions"

    def test_no_frontmatter_returns_all(self):
        content = "No frontmatter just body"
        assert _extract_body(content) == content

    def test_empty_body(self):
        content = "---\nname: test\n---\n"
        assert _extract_body(content) == ""


# ---------------------------------------------------------------------------
# SkillLoader
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSkillLoader:

    def test_discovers_skills_from_directory(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "review", "Review code")
        _create_skill(skills_dir, "commit", "Create commit")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        names = {s.name for s in skills}
        assert "review" in names
        assert "commit" in names

    def test_deduplicates_by_name(self, tmp_path: Path):
        # Same skill in two dirs — first one wins
        dir1 = tmp_path / "skills1"
        dir2 = tmp_path / "skills2"
        _create_skill(dir1, "review", "First version")
        _create_skill(dir2, "review", "Second version")

        loader = SkillLoader(skill_dirs=["skills1", "skills2"], base_dir=tmp_path)
        skills = loader.load_all()

        reviews = [s for s in skills if s.name == "review"]
        assert len(reviews) == 1
        assert reviews[0].description == "First version"

    def test_skips_non_skill_directories(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        skills_dir.mkdir()
        # File, not directory
        (skills_dir / "not_a_skill.txt").write_text("nope")
        # Directory without SKILL.md
        (skills_dir / "empty_dir").mkdir()

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()
        assert len(skills) == 0

    def test_loads_metadata_only(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "test-skill", "Test description", body="Heavy body content")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        assert len(skills) == 1
        assert skills[0].name == "test-skill"
        assert skills[0].description == "Test description"
        # Body should NOT be loaded yet (lazy loading)
        assert skills[0]._body is None

    def test_get_by_name(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "find-me", "Find me skill")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        found = loader.get_by_name("find-me", skills)
        assert found is not None
        assert found.name == "find-me"

        assert loader.get_by_name("nonexistent", skills) is None

    def test_get_invocable(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "invocable", user_invocable=True)
        _create_skill(skills_dir, "background", user_invocable=False)

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()
        invocable = loader.get_invocable(skills)

        names = {s.name for s in invocable}
        assert "invocable" in names
        assert "background" not in names

    def test_get_model_available(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "visible", disable_model_invocation=False)
        _create_skill(skills_dir, "hidden", disable_model_invocation=True)

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()
        model_available = loader.get_model_available(skills)

        names = {s.name for s in model_available}
        assert "visible" in names
        assert "hidden" not in names


# ---------------------------------------------------------------------------
# Skill rendering
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSkillRendering:

    def test_load_body_on_demand(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "lazy", body="Lazy body content here")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()
        skill = skills[0]

        assert skill._body is None
        body = skill.load_body()
        assert "Lazy body content here" in body
        assert skill._body is not None  # cached

    def test_render_with_arguments(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "greet", body="Say hello to $ARGUMENTS")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        rendered = skills[0].render("World")
        assert "Say hello to World" in rendered

    def test_render_with_positional_args(self, tmp_path: Path):
        # $0/$1 substitution requires $ARGUMENTS to be present in the body
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "pos", body="All: $ARGUMENTS | First: $0, Second: $1")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        rendered = skills[0].render("foo bar")
        assert "All: foo bar" in rendered
        assert "First: foo" in rendered
        assert "Second: bar" in rendered

    def test_render_no_placeholder_appends(self, tmp_path: Path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "plain", body="No placeholders here")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        rendered = skills[0].render("extra args")
        assert "No placeholders here" in rendered
        assert "ARGUMENTS: extra args" in rendered

    def test_render_empty_body(self):
        skill = Skill(name="empty", skill_dir=None)
        assert skill.render("args") == ""

    def test_dynamic_context_resolution(self):
        body = "Today is !`echo hello_world`."
        result = _resolve_dynamic_context(body)
        assert "hello_world" in result

    def test_dynamic_context_failed_command(self):
        body = "Result: !`exit 1`"
        result = _resolve_dynamic_context(body)
        assert "command failed" in result


# ---------------------------------------------------------------------------
# Skill invocation through agent loop
# ---------------------------------------------------------------------------

@pytest.mark.integration
class TestSkillInvocation:

    async def test_skill_command_routes_to_invoke(self, fake_llm, fake_cli, test_config, tmp_path):
        skills_dir = tmp_path / "skills"
        _create_skill(skills_dir, "review", "Review code", body="Please review $ARGUMENTS")

        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        skills = loader.load_all()

        fake_llm.set_text_response("Code looks good!")
        agent = build_agent(
            fake_llm, fake_cli, test_config, tmp_path,
            skill_loader=loader, skills=skills,
        )

        handled = await agent._handle_command("/review auth.py")
        assert handled is True

        # The rendered skill body should have been processed as a user message
        msgs = agent._conversation.messages
        assert len(msgs) == 2
        assert "review auth.py" in msgs[0].text.lower() or "auth.py" in msgs[0].text

    async def test_unknown_skill_not_handled(self, fake_llm, fake_cli, test_config, tmp_path):
        loader = SkillLoader(skill_dirs=["skills"], base_dir=tmp_path)
        agent = build_agent(
            fake_llm, fake_cli, test_config, tmp_path,
            skill_loader=loader, skills=[],
        )

        handled = await agent._handle_command("/nonexistent_skill")
        assert handled is False
