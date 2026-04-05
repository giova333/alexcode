"""Tests for WebFetch and WebSearch tools."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest


# ---------------------------------------------------------------------------
# WebFetchTool tests
# ---------------------------------------------------------------------------

class TestWebFetchTool:
    @pytest.fixture
    def tool(self):
        from agent.tools.builtin.web_fetch import WebFetchTool
        return WebFetchTool(timeout=10, max_content_length=1000)

    def _mock_response(self, mocker, *, status_code=200, content_type="text/html", text=""):
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.headers = {"content-type": content_type}
        mock_response.text = text
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        mocker.patch("agent.tools.builtin.web_fetch.httpx.AsyncClient", return_value=mock_client)
        return mock_client, mock_response

    @pytest.mark.asyncio
    async def test_fetch_html_page(self, tool, mocker):
        self._mock_response(
            mocker,
            text="<html><body><h1>Title</h1><p>Hello world</p></body></html>",
        )
        result = await tool.execute(url="https://example.com")
        assert "Hello world" in result
        assert "<p>" not in result

    @pytest.mark.asyncio
    async def test_fetch_plain_text(self, tool, mocker):
        self._mock_response(
            mocker,
            content_type="text/plain",
            text="Plain text content here",
        )
        result = await tool.execute(url="https://example.com/file.txt")
        assert "Plain text content here" in result

    @pytest.mark.asyncio
    async def test_fetch_json(self, tool, mocker):
        self._mock_response(
            mocker,
            content_type="application/json",
            text='{"key": "value"}',
        )
        result = await tool.execute(url="https://api.example.com/data")
        assert '"key": "value"' in result

    @pytest.mark.asyncio
    async def test_fetch_with_prompt(self, tool, mocker):
        self._mock_response(
            mocker,
            content_type="text/plain",
            text="Some content",
        )
        result = await tool.execute(url="https://example.com", prompt="What is the price?")
        assert result.startswith("[Extraction focus: What is the price?]")
        assert "Some content" in result

    @pytest.mark.asyncio
    async def test_fetch_truncation(self, tool, mocker):
        self._mock_response(
            mocker,
            content_type="text/plain",
            text="A" * 2000,
        )
        result = await tool.execute(url="https://example.com")
        assert "content truncated at 1000 characters" in result
        # Content before truncation message should be at most max_content_length
        assert result.startswith("A" * 1000)

    @pytest.mark.asyncio
    async def test_fetch_invalid_url(self, tool):
        result = await tool.execute(url="ftp://example.com/file")
        assert "Error" in result
        assert "http://" in result

    @pytest.mark.asyncio
    async def test_fetch_binary_content_type(self, tool, mocker):
        self._mock_response(
            mocker,
            content_type="image/png",
            text="binary data",
        )
        result = await tool.execute(url="https://example.com/image.png")
        assert "Error" in result
        assert "non-text" in result

    @pytest.mark.asyncio
    async def test_fetch_timeout(self, tool, mocker):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        mocker.patch("agent.tools.builtin.web_fetch.httpx.AsyncClient", return_value=mock_client)

        result = await tool.execute(url="https://example.com")
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_fetch_http_error(self, tool, mocker):
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Not Found", request=MagicMock(), response=mock_response
            )
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        mocker.patch("agent.tools.builtin.web_fetch.httpx.AsyncClient", return_value=mock_client)

        result = await tool.execute(url="https://example.com/missing")
        assert "404" in result

    @pytest.mark.asyncio
    async def test_fetch_connect_error(self, tool, mocker):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("refused"))

        mocker.patch("agent.tools.builtin.web_fetch.httpx.AsyncClient", return_value=mock_client)

        result = await tool.execute(url="https://unreachable.example.com")
        assert "Could not connect" in result


# ---------------------------------------------------------------------------
# WebSearchTool tests
# ---------------------------------------------------------------------------

class TestWebSearchTool:
    @pytest.fixture
    def brave_tool(self):
        from agent.tools.builtin.web_search import WebSearchTool
        return WebSearchTool(api_key="test-key", provider="brave", timeout=10)

    @pytest.fixture
    def ddg_tool(self):
        from agent.tools.builtin.web_search import WebSearchTool
        return WebSearchTool(api_key="", provider="brave", timeout=10)

    def _mock_brave_response(self, mocker, *, results=None, status_code=200):
        data = {
            "web": {
                "results": results or []
            }
        }
        mock_response = MagicMock()
        mock_response.status_code = status_code
        mock_response.json = MagicMock(return_value=data)
        mock_response.raise_for_status = MagicMock()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        mocker.patch("agent.tools.builtin.web_search.httpx.AsyncClient", return_value=mock_client)
        return mock_client

    @pytest.mark.asyncio
    async def test_brave_search_success(self, brave_tool, mocker):
        self._mock_brave_response(mocker, results=[
            {"title": "Python Docs", "url": "https://python.org", "description": "Official Python documentation"},
            {"title": "PyPI", "url": "https://pypi.org", "description": "Python package index"},
        ])
        result = await brave_tool.execute(query="python")
        assert "1. Python Docs" in result
        assert "https://python.org" in result
        assert "2. PyPI" in result
        assert "Official Python documentation" in result

    @pytest.mark.asyncio
    async def test_brave_search_no_results(self, brave_tool, mocker):
        self._mock_brave_response(mocker, results=[])
        result = await brave_tool.execute(query="xyznonexistent123")
        assert "No results" in result

    @pytest.mark.asyncio
    async def test_brave_search_timeout(self, brave_tool, mocker):
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=httpx.TimeoutException("timeout"))

        mocker.patch("agent.tools.builtin.web_search.httpx.AsyncClient", return_value=mock_client)

        result = await brave_tool.execute(query="test")
        assert "timed out" in result

    @pytest.mark.asyncio
    async def test_brave_search_rate_limited(self, brave_tool, mocker):
        mock_response = MagicMock()
        mock_response.status_code = 429
        mock_response.raise_for_status = MagicMock(
            side_effect=httpx.HTTPStatusError(
                "Rate limited", request=MagicMock(), response=mock_response
            )
        )

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(return_value=mock_response)

        mocker.patch("agent.tools.builtin.web_search.httpx.AsyncClient", return_value=mock_client)

        result = await brave_tool.execute(query="test")
        assert "rate limited" in result.lower()

    @pytest.mark.asyncio
    async def test_max_results_clamped(self, brave_tool, mocker):
        self._mock_brave_response(mocker, results=[
            {"title": f"Result {i}", "url": f"https://example.com/{i}", "description": f"Desc {i}"}
            for i in range(25)
        ])
        mock_client = mocker.patch("agent.tools.builtin.web_search.httpx.AsyncClient")
        # Re-mock to capture params
        inner_client = AsyncMock()
        inner_client.__aenter__ = AsyncMock(return_value=inner_client)
        inner_client.__aexit__ = AsyncMock(return_value=False)

        resp = MagicMock()
        resp.status_code = 200
        resp.json = MagicMock(return_value={"web": {"results": [
            {"title": f"R{i}", "url": f"https://e.com/{i}", "description": f"D{i}"}
            for i in range(25)
        ]}})
        resp.raise_for_status = MagicMock()
        inner_client.get = AsyncMock(return_value=resp)
        mock_client.return_value = inner_client

        result = await brave_tool.execute(query="test", max_results=50)
        # Should have at most 20 results (clamped)
        assert "21." not in result

    @pytest.mark.asyncio
    async def test_no_api_key_uses_duckduckgo(self, ddg_tool, mocker):
        """When no API key is set, should fall back to DuckDuckGo."""
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = """
        <table>
            <tr><td><a class="result-link" href="https://example.com">Example Site</a></td></tr>
            <tr><td class="result-snippet">This is an example website.</td></tr>
        </table>
        """
        mock_response.raise_for_status = MagicMock()
        mock_client.post = AsyncMock(return_value=mock_response)

        mocker.patch("agent.tools.builtin.web_search.httpx.AsyncClient", return_value=mock_client)

        result = await ddg_tool.execute(query="example")
        # Should have used POST (DuckDuckGo) not GET (Brave)
        mock_client.post.assert_called_once()
        assert "Example Site" in result

    @pytest.mark.asyncio
    async def test_tool_properties(self, brave_tool):
        assert brave_tool.name == "web_search"
        assert "query" in brave_tool.input_schema["properties"]
        assert "query" in brave_tool.input_schema["required"]

    @pytest.mark.asyncio
    async def test_webfetch_tool_properties(self):
        from agent.tools.builtin.web_fetch import WebFetchTool
        tool = WebFetchTool()
        assert tool.name == "web_fetch"
        assert "url" in tool.input_schema["properties"]
        assert "url" in tool.input_schema["required"]
