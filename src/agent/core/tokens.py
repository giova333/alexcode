"""Token counting utilities."""

from __future__ import annotations

import json

import tiktoken


_encoder: tiktoken.Encoding | None = None


def _get_encoder() -> tiktoken.Encoding:
    global _encoder
    if _encoder is None:
        _encoder = tiktoken.get_encoding("cl100k_base")
    return _encoder


def count_tokens(text: str) -> int:
    """Count tokens in a text string."""
    return len(_get_encoder().encode(text))


def count_message_tokens(message: dict) -> int:
    """Estimate token count for a message dict (role + content blocks)."""
    total = 4  # overhead per message
    content = message.get("content", [])
    if isinstance(content, str):
        total += count_tokens(content)
    elif isinstance(content, list):
        for block in content:
            if isinstance(block, dict):
                if block.get("type") == "text":
                    total += count_tokens(block.get("text", ""))
                else:
                    total += count_tokens(json.dumps(block))
            elif isinstance(block, str):
                total += count_tokens(block)
    return total
