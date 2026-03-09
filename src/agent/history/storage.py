"""Conversation history persistence as JSON files."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.message import Message


class HistoryStorage:
    """Saves and loads conversation histories as JSON."""

    def __init__(self, history_dir: str, base_dir: Path) -> None:
        self._dir = base_dir / history_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def new_session_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    def save(self, session_id: str, messages: list[Message], metadata: dict[str, Any] | None = None) -> Path:
        """Save a conversation to a JSON file."""
        path = self._dir / f"{session_id}.json"
        data = {
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
            "messages": [
                {
                    "role": msg.role,
                    "content": msg.content,
                    "token_count": msg.token_count,
                }
                for msg in messages
            ],
        }
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False))
        return path

    def load(self, session_id: str) -> list[Message] | None:
        """Load a conversation from a JSON file."""
        path = self._dir / f"{session_id}.json"
        if not path.exists():
            return None

        data = json.loads(path.read_text())
        messages = []
        for msg_data in data.get("messages", []):
            msg = Message(
                role=msg_data["role"],
                content=msg_data["content"],
                token_count=msg_data.get("token_count", 0),
            )
            messages.append(msg)
        return messages

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions (newest first)."""
        files = sorted(self._dir.glob("*.json"), key=lambda f: f.stat().st_mtime, reverse=True)
        sessions = []
        for f in files[:limit]:
            try:
                data = json.loads(f.read_text())
                sessions.append({
                    "session_id": data.get("session_id", f.stem),
                    "timestamp": data.get("timestamp", ""),
                    "message_count": len(data.get("messages", [])),
                })
            except (json.JSONDecodeError, KeyError):
                continue
        return sessions
