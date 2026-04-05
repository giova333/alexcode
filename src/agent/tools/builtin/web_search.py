"""WebSearch tool — search the web and return results."""

from __future__ import annotations

import os
from typing import Any

import httpx


class WebSearchTool:
    def __init__(
        self,
        provider: str = "brave",
        api_key: str = "",
        default_max_results: int = 5,
        timeout: int = 15,
        user_agent: str = "Mozilla/5.0 (compatible; AgentCLI/0.1)",
    ) -> None:
        self._provider = provider
        self._api_key = api_key or os.environ.get("BRAVE_SEARCH_API_KEY", "")
        self._default_max_results = default_max_results
        self._timeout = timeout
        self._user_agent = user_agent

    @property
    def name(self) -> str:
        return "web_search"

    @property
    def description(self) -> str:
        return (
            "Search the web and return results with titles, URLs, and snippets. "
            "Uses Brave Search API when configured, otherwise falls back to DuckDuckGo."
        )

    @property
    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "The search query.",
                },
                "max_results": {
                    "type": "integer",
                    "description": "Maximum number of results to return (default: 5, max: 20).",
                },
            },
            "required": ["query"],
        }

    async def execute(self, *, query: str, max_results: int | None = None, **_: Any) -> str:
        count = min(max_results or self._default_max_results, 20)

        if self._api_key and self._provider == "brave":
            return await self._search_brave(query, count)
        return await self._search_duckduckgo(query, count)

    async def _search_brave(self, query: str, count: int) -> str:
        """Search using the Brave Search API."""
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                headers={
                    "X-Subscription-Token": self._api_key,
                    "Accept": "application/json",
                    "User-Agent": self._user_agent,
                },
            ) as client:
                response = await client.get(
                    "https://api.search.brave.com/res/v1/web/search",
                    params={"q": query, "count": count},
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            return f"Error: Search request timed out for query: {query}"
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                return "Error: Search API rate limited. Try again later."
            return f"Error: Search API returned HTTP {exc.response.status_code}"
        except httpx.RequestError as exc:
            return f"Error: Search request failed: {exc}"

        data = response.json()
        results = data.get("web", {}).get("results", [])

        if not results:
            return f"No results found for: {query}"

        return self._format_results(results[:count])

    async def _search_duckduckgo(self, query: str, count: int) -> str:
        """Search using DuckDuckGo HTML lite (no API key needed)."""
        try:
            async with httpx.AsyncClient(
                timeout=self._timeout,
                follow_redirects=True,
                headers={"User-Agent": self._user_agent},
            ) as client:
                response = await client.post(
                    "https://lite.duckduckgo.com/lite/",
                    data={"q": query},
                )
                response.raise_for_status()
        except httpx.TimeoutException:
            return f"Error: Search request timed out for query: {query}"
        except httpx.RequestError as exc:
            return f"Error: Search request failed: {exc}"

        return self._parse_duckduckgo_html(response.text, count)

    def _parse_duckduckgo_html(self, html: str, count: int) -> str:
        """Parse DuckDuckGo lite HTML response to extract results."""
        from html.parser import HTMLParser

        class DDGParser(HTMLParser):
            def __init__(self) -> None:
                super().__init__()
                self.results: list[dict[str, str]] = []
                self._current: dict[str, str] = {}
                self._in_result_link = False
                self._in_snippet = False
                self._text_parts: list[str] = []

            def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
                attr_dict = dict(attrs)
                if tag == "a" and attr_dict.get("class") == "result-link":
                    self._in_result_link = True
                    self._current["url"] = attr_dict.get("href", "")
                    self._text_parts = []
                elif tag == "td" and attr_dict.get("class") == "result-snippet":
                    self._in_snippet = True
                    self._text_parts = []

            def handle_endtag(self, tag: str) -> None:
                if tag == "a" and self._in_result_link:
                    self._in_result_link = False
                    self._current["title"] = "".join(self._text_parts).strip()
                elif tag == "td" and self._in_snippet:
                    self._in_snippet = False
                    self._current["snippet"] = "".join(self._text_parts).strip()
                    if self._current.get("title") and self._current.get("url"):
                        self.results.append(self._current)
                    self._current = {}

            def handle_data(self, data: str) -> None:
                if self._in_result_link or self._in_snippet:
                    self._text_parts.append(data)

        parser = DDGParser()
        parser.feed(html)

        if not parser.results:
            return f"No results found for the query."

        return self._format_results(parser.results[:count])

    def _format_results(self, results: list[dict[str, str]]) -> str:
        """Format search results as numbered list."""
        lines: list[str] = []
        for i, result in enumerate(results, 1):
            title = result.get("title", "Untitled")
            url = result.get("url", "")
            snippet = result.get("description") or result.get("snippet", "")
            lines.append(f"{i}. {title}")
            lines.append(f"   URL: {url}")
            if snippet:
                lines.append(f"   {snippet}")
            lines.append("")
        return "\n".join(lines).strip()
