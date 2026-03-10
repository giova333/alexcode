"""OAuth browser flow support for MCP HTTP servers."""

from __future__ import annotations

import json
import threading
import webbrowser
from asyncio import Event, get_running_loop
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import parse_qs, urlparse

from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


class FileTokenStorage:
    """Persist OAuth tokens and client info to disk."""

    def __init__(self, server_name: str, base_dir: Path | None = None) -> None:
        self._dir = (base_dir or Path(".agent/oauth")) / server_name
        self._dir.mkdir(parents=True, exist_ok=True)

    def _tokens_path(self) -> Path:
        return self._dir / "tokens.json"

    def _client_path(self) -> Path:
        return self._dir / "client.json"

    async def get_tokens(self) -> OAuthToken | None:
        path = self._tokens_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return OAuthToken(**data)
        except (json.JSONDecodeError, Exception):
            return None

    async def set_tokens(self, tokens: OAuthToken) -> None:
        self._tokens_path().write_text(tokens.model_dump_json(indent=2))

    async def get_client_info(self) -> OAuthClientInformationFull | None:
        path = self._client_path()
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text())
            return OAuthClientInformationFull(**data)
        except (json.JSONDecodeError, Exception):
            return None

    async def set_client_info(self, client_info: OAuthClientInformationFull) -> None:
        self._client_path().write_text(client_info.model_dump_json(indent=2))


CALLBACK_PORT = 18247  # Arbitrary high port for OAuth callback


async def open_browser_redirect(url: str) -> None:
    """Open the authorization URL in the user's default browser."""
    print("Opening browser for authentication...")
    webbrowser.open(url)


async def wait_for_callback() -> tuple[str, str | None]:
    """Run a temporary local HTTP server to receive the OAuth callback.

    Returns (auth_code, state).
    """
    loop = get_running_loop()
    done = Event()
    result: dict[str, Any] = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            qs = parse_qs(urlparse(self.path).query)
            result["code"] = qs.get("code", [None])[0]
            result["state"] = qs.get("state", [None])[0]

            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.end_headers()
            self.wfile.write(
                b"<html><body><h2>Authentication successful!</h2>"
                b"<p>You can close this tab and return to the agent.</p>"
                b"<script>window.close()</script></body></html>"
            )
            loop.call_soon_threadsafe(done.set)

        def log_message(self, format: str, *args: Any) -> None:
            pass  # Suppress HTTP server logs

    server = HTTPServer(("127.0.0.1", CALLBACK_PORT), Handler)

    def _serve_until_done() -> None:
        while not done.is_set():
            server.handle_request()
        server.server_close()

    # Run blocking server in a thread
    thread = threading.Thread(target=_serve_until_done, daemon=True)
    thread.start()

    # Wait for the callback asynchronously
    await done.wait()

    code = result.get("code", "")
    state = result.get("state")
    if not code:
        raise RuntimeError("No authorization code received from OAuth callback")
    return code, state
