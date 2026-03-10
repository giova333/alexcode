"""Conversation history persistence as JSONL files (one JSON object per line)."""

from __future__ import annotations

import json
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from agent.core.message import Message


class HistoryStorage:
    """Saves and loads conversation histories as JSONL.

    Format:
      Line 1: header  {"type": "header", "session_id": "...", "timestamp": "...", "metadata": {...}}
      Line 2+: messages {"type": "message", "role": "...", "content": ..., "token_count": N}

    Appending new messages is O(new_messages) — no need to rewrite the file.
    """

    def __init__(self, history_dir: str, base_dir: Path) -> None:
        self._dir = base_dir / history_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def new_session_id(self) -> str:
        return datetime.now().strftime("%Y%m%d_%H%M%S") + "_" + uuid.uuid4().hex[:8]

    def save(self, session_id: str, messages: list[Message], metadata: dict[str, Any] | None = None) -> Path:
        """Append new messages to a JSONL session file.

        Only messages not yet written are appended, making repeated saves efficient.
        """
        path = self._dir / f"{session_id}.jsonl"
        existing_count = 0

        if path.exists():
            # Count existing message lines (skip header)
            with path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        if obj.get("type") == "message":
                            existing_count += 1
                    except json.JSONDecodeError:
                        continue
        else:
            # Write header as first line
            header = {
                "type": "header",
                "session_id": session_id,
                "timestamp": datetime.now().isoformat(),
                "metadata": metadata or {},
            }
            with path.open("w", encoding="utf-8") as f:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")

        # Append only new messages
        new_messages = messages[existing_count:]
        if new_messages:
            with path.open("a", encoding="utf-8") as f:
                for msg in new_messages:
                    record = {
                        "type": "message",
                        "role": msg.role,
                        "content": msg.content,
                        "token_count": msg.token_count,
                    }
                    f.write(json.dumps(record, ensure_ascii=False) + "\n")

        return path

    def rewrite(self, session_id: str, messages: list[Message], metadata: dict[str, Any] | None = None) -> Path:
        """Rewrite a session file from scratch (e.g. after compaction).

        Unlike save(), this replaces the entire file instead of appending.
        """
        path = self._dir / f"{session_id}.jsonl"
        header = {
            "type": "header",
            "session_id": session_id,
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
        }
        with path.open("w", encoding="utf-8") as f:
            f.write(json.dumps(header, ensure_ascii=False) + "\n")
            for msg in messages:
                record = {
                    "type": "message",
                    "role": msg.role,
                    "content": msg.content,
                    "token_count": msg.token_count,
                }
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return path

    def load(self, session_id: str) -> list[Message] | None:
        """Load a conversation from a JSONL file."""
        path = self._dir / f"{session_id}.jsonl"
        if not path.exists():
            # Fallback: try legacy .json format
            return self._load_legacy_json(session_id)

        messages = []
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") != "message":
                    continue
                msg = Message(
                    role=obj["role"],
                    content=obj["content"],
                    token_count=obj.get("token_count", 0),
                )
                messages.append(msg)
        return messages if messages else None

    def _load_legacy_json(self, session_id: str) -> list[Message] | None:
        """Load from old .json format for backwards compatibility."""
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

    def clear_session(self, session_id: str) -> None:
        """Reset a session file to header-only (no messages)."""
        path = self._dir / f"{session_id}.jsonl"
        if not path.exists():
            return
        # Read header, rewrite file with header only
        header = None
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    if obj.get("type") == "header":
                        header = obj
                        break
                except json.JSONDecodeError:
                    continue
        if header:
            with path.open("w", encoding="utf-8") as f:
                f.write(json.dumps(header, ensure_ascii=False) + "\n")

    def find_session(self, query: str) -> str | None:
        """Find a session ID by exact or prefix match. Returns full ID or None."""
        # Exact match (prefer .jsonl, fallback to .json)
        if (self._dir / f"{query}.jsonl").exists():
            return query
        if (self._dir / f"{query}.json").exists():
            return query
        # Prefix match
        matches = sorted(
            list(self._dir.glob(f"{query}*.jsonl")) + list(self._dir.glob(f"{query}*.json")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if matches:
            return matches[0].stem
        return None

    def get_latest_session_id(self) -> str | None:
        """Return the most recent session ID, or None if no sessions exist."""
        files = sorted(
            list(self._dir.glob("*.jsonl")) + list(self._dir.glob("*.json")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        return files[0].stem if files else None

    def list_sessions(self, limit: int = 20) -> list[dict[str, Any]]:
        """List recent sessions (newest first)."""
        files = sorted(
            list(self._dir.glob("*.jsonl")) + list(self._dir.glob("*.json")),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        sessions = []
        for f in files[:limit]:
            try:
                if f.suffix == ".jsonl":
                    sessions.append(self._session_info_jsonl(f))
                else:
                    sessions.append(self._session_info_json(f))
            except Exception:
                continue
        return sessions

    def _session_info_jsonl(self, path: Path) -> dict[str, Any]:
        """Extract session info from a JSONL file (reads only what's needed)."""
        session_id = path.stem
        timestamp = ""
        message_count = 0
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if obj.get("type") == "header":
                    session_id = obj.get("session_id", session_id)
                    timestamp = obj.get("timestamp", "")
                elif obj.get("type") == "message":
                    message_count += 1
        return {
            "session_id": session_id,
            "timestamp": timestamp,
            "message_count": message_count,
        }

    def _session_info_json(self, path: Path) -> dict[str, Any]:
        """Extract session info from a legacy JSON file."""
        data = json.loads(path.read_text())
        return {
            "session_id": data.get("session_id", path.stem),
            "timestamp": data.get("timestamp", ""),
            "message_count": len(data.get("messages", [])),
        }
