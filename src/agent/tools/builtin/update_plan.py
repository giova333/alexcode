"""Plan mode tool: writes/updates the structured plan file."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


VALID_STATUSES = {"pending", "in_progress", "completed"}


class UpdatePlanTool:
    """Update the current plan during plan mode."""

    name = "update_plan"
    description = (
        "Update the current plan. Provide an explanation and a list of steps with statuses. "
        "Each step has a 'step' (description) and 'status' (pending, in_progress, or completed). "
        "Always send the full plan — it replaces the previous version."
    )
    input_schema: dict[str, Any] = {
        "type": "object",
        "properties": {
            "explanation": {
                "type": "string",
                "description": "High-level explanation of the plan approach.",
            },
            "plan": {
                "type": "array",
                "description": "Ordered list of plan steps.",
                "items": {
                    "type": "object",
                    "properties": {
                        "step": {
                            "type": "string",
                            "description": "Description of this step.",
                        },
                        "status": {
                            "type": "string",
                            "enum": ["pending", "in_progress", "completed"],
                            "description": "Current status of this step.",
                        },
                    },
                    "required": ["step", "status"],
                },
            },
        },
        "required": ["explanation", "plan"],
    }

    def __init__(self) -> None:
        self._plan_file: Path | None = None

    def set_plan_file(self, path: Path | None) -> None:
        """Set the target plan file path. Pass None to disable."""
        self._plan_file = path

    async def execute(self, **kwargs: Any) -> str:
        explanation: str = kwargs["explanation"]
        plan: list[dict[str, str]] = kwargs["plan"]

        if self._plan_file is None:
            return "Error: not in plan mode. Use /plan to enter plan mode first."

        # Validate steps
        for i, entry in enumerate(plan):
            if "step" not in entry or "status" not in entry:
                return f"Error: step {i} must have 'step' and 'status' fields."
            if entry["status"] not in VALID_STATUSES:
                return f"Error: step {i} has invalid status '{entry['status']}'. Use: {', '.join(VALID_STATUSES)}"

        data = {"explanation": explanation, "plan": plan}
        self._plan_file.parent.mkdir(parents=True, exist_ok=True)
        self._plan_file.write_text(json.dumps(data, indent=2))

        completed = sum(1 for s in plan if s["status"] == "completed")
        in_progress = sum(1 for s in plan if s["status"] == "in_progress")
        pending = sum(1 for s in plan if s["status"] == "pending")
        return f"Plan updated ({len(plan)} steps: {completed} completed, {in_progress} in progress, {pending} pending)."
