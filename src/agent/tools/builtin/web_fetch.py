"""WebFetch tool — fetch a URL and return page content as readable text."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from typing import Any

import httpx


class _HTMLTextExtractor(HTMLParser):
    """Minimal HTML-to-text using only stdlib (fallback)."""

    _SKIP_TAGS = frozenset({"script", "style", "head", "noscript"})
    _BLOCK_TAGS = frozenset({"br", "p", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "tr", "blockquote", "pre"})

    def __init__(self) -> None:
        super().__init__()
        self._pieces: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        elif tag in self._BLOCK_TAGS:
            self._pieces.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            self._pieces.append(data)

    def get_text(self) -> str:
        text = "".join(self._pieces)
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()


def _html_to_text(html: str) -> str:
    """Convert HTML to readable text. Uses html2text if available, else stdlib."""
    try:
        import html2text

        converter = html2text.HTML2Text()
        converter.body_width = 0
        converter.ignore_images = True
        converter.ignore_emphasis = False
        converter.skip_internal_links = True
        return converter.handle(html).strip()
    except ImportError:
        extractor = _HTMLTextExtractor()
        extractor.feed(html)
        return extractor.get_text()


_TEXT_CONTENT_TYPES = frozenset({"text/html", "text/plain", "application/json", "application/xml", "text/xml", "text/csv"})


def _is_text_response(content_type: str) -> bool:
    """Check if the content type is text-based."""
    base = content_type.split(";")[0].strip().lower()
    return base in _TEXT_CONTENT_TYPES or base.startswith("text/")


class WebFetchTool:
    def __init__(
        self,
        timeout: int = 30,
        max_content_length: int = 50_000,
        user_agent: str = "Mozilla/5.0 (compatible; AgentCLI/0.1)",
    ) -> None:
        self._timeout = timeout
        self._max_content_length = max_content_length
        self._user_agent = user_agent

    @property
    def name(self) -> str:
        return "web_fetch"

    @property
    def description(self) -> str:
        return (
            "Fetch a URL and return the page content as readable text. "
            "Supports HTML pages (converted to text), plain text, and JSON. "
            "Use the optional 'prompt' parameter to indicate what information you are looking for."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch (must be http:// or https://).",
                },
                "prompt": {
                    "type": "string",
                    "description": "Optional question or focus area to guide content extraction.",
                },
            },
            "required": ["url"],
        }

    async def execute(self, *, url: str, prompt: str | None = None, **_: Any) -> str:
        if not url.startswith(("http://", "https://")):
            return "Error: URL must start with http:// or https://"

        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            ) as client:
                response = await client.get(url)
                response.raise_for_status()
        except httpx.TimeoutException:
            return f"Error: Request timed out after {self._timeout}s for {url}"
        except httpx.ConnectError:
            return f"Error: Could not connect to {url}"
        except httpx.HTTPStatusError as exc:
            return f"Error: HTTP {exc.response.status_code} for {url}"
        except httpx.RequestError as exc:
            return f"Error: Request failed for {url}: {exc}"

        content_type = response.headers.get("content-type", "text/plain")

        if not _is_text_response(content_type):
            base = content_type.split(";")[0].strip()
            return f"Error: URL returned non-text content ({base}), cannot extract text."

        raw = response.text

        # Convert HTML to readable text
        base_type = content_type.split(";")[0].strip().lower()
        if base_type == "text/html":
            text = _html_to_text(raw)
        else:
            text = raw

        # Truncate if needed
        if len(text) > self._max_content_length:
            text = text[: self._max_content_length] + f"\n\n... (content truncated at {self._max_content_length} characters)"

        # Prepend prompt context
        if prompt:
            text = f"[Extraction focus: {prompt}]\n\n{text}"

        return text or "(empty page)"
