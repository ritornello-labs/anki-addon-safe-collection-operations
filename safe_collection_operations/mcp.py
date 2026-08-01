"""Small, optional, authenticated MCP adapter over the operation registry."""

from __future__ import annotations

import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from .service import DesktopService


SUPPORTED_PROTOCOL_VERSIONS = ("2025-06-18", "2024-11-05")


class MCPServer:
    def __init__(
        self,
        service: DesktopService,
        *,
        host: str = "127.0.0.1",
        port: int = 0,
        discovery_file: Path | None = None,
    ) -> None:
        self.service = service
        self.host = host
        self.port = int(port)
        self.token = secrets.token_urlsafe(32)
        self.discovery_file = discovery_file
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str | None:
        if self._httpd is None:
            return None
        return f"http://{self.host}:{self._httpd.server_address[1]}/mcp"

    def start(self) -> None:
        if self._httpd is not None:
            return
        outer = self

        class Handler(BaseHTTPRequestHandler):
            server_version = "anki-safe-collection-operations-mcp/1"

            def log_message(self, _format: str, *_args: Any) -> None:
                return

            def do_POST(self) -> None:  # noqa: N802
                if self.path != "/mcp":
                    self.send_error(HTTPStatus.NOT_FOUND)
                    return
                if self.headers.get("Authorization") != f"Bearer {outer.token}":
                    self._send_json(
                        HTTPStatus.UNAUTHORIZED,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32001, "message": "unauthorized"},
                        },
                    )
                    return
                try:
                    length = int(self.headers.get("Content-Length", "0"))
                    if length <= 0 or length > 1_000_000:
                        raise ValueError("invalid request size")
                    request = json.loads(self.rfile.read(length).decode("utf-8"))
                    if not isinstance(request, dict):
                        raise ValueError("request must be an object")
                    response = outer._handle(request)
                    if response is None:
                        self.send_response(HTTPStatus.ACCEPTED)
                        self.send_header("Content-Length", "0")
                        self.end_headers()
                    else:
                        self._send_json(HTTPStatus.OK, response)
                except Exception as exc:
                    self._send_json(
                        HTTPStatus.BAD_REQUEST,
                        {
                            "jsonrpc": "2.0",
                            "id": None,
                            "error": {"code": -32600, "message": str(exc)},
                        },
                    )

            def _send_json(self, status: HTTPStatus, value: dict[str, Any]) -> None:
                data = json.dumps(value, ensure_ascii=False).encode("utf-8")
                self.send_response(status)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(data)))
                self.end_headers()
                self.wfile.write(data)

        self._httpd = ThreadingHTTPServer((self.host, self.port), Handler)
        self._thread = threading.Thread(
            target=self._httpd.serve_forever,
            name="anki-safe-collection-operations-mcp",
            daemon=True,
        )
        self._thread.start()
        self._write_discovery()

    def stop(self) -> None:
        if self._httpd is None:
            return
        self._httpd.shutdown()
        self._httpd.server_close()
        if self._thread is not None:
            self._thread.join(timeout=2)
        self._httpd = None
        self._thread = None
        if self.discovery_file is not None:
            self.discovery_file.unlink(missing_ok=True)

    def _write_discovery(self) -> None:
        if self.discovery_file is None or self.url is None:
            return
        self.discovery_file.parent.mkdir(parents=True, exist_ok=True)
        self.discovery_file.write_text(
            json.dumps(
                {
                    "url": self.url,
                    "authorization": f"Bearer {self.token}",
                    "note": "Ephemeral local credential; regenerated when Anki starts.",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )

    def _handle(self, request: dict[str, Any]) -> dict[str, Any] | None:
        method = str(request.get("method", ""))
        request_id = request.get("id")
        if method.startswith("notifications/"):
            return None
        if method == "initialize":
            requested = str((request.get("params") or {}).get("protocolVersion", ""))
            protocol = (
                requested
                if requested in SUPPORTED_PROTOCOL_VERSIONS
                else SUPPORTED_PROTOCOL_VERSIONS[0]
            )
            result = {
                "protocolVersion": protocol,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "anki-safe-collection-operations",
                    "version": "0.2.0",
                },
            }
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        if method == "ping":
            return {"jsonrpc": "2.0", "id": request_id, "result": {}}
        if method == "tools/list":
            tools = [spec.mcp_tool() for spec in self.service.registry.specs()]
            return {"jsonrpc": "2.0", "id": request_id, "result": {"tools": tools}}
        if method == "tools/call":
            params = request.get("params") or {}
            name = str(params.get("name", ""))
            arguments = params.get("arguments") or {}
            if not isinstance(arguments, dict):
                raise ValueError("tool arguments must be an object")
            try:
                value = self.service.execute_on_main(name, arguments)
                content = [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]
                result = {"content": content, "isError": False}
            except Exception as exc:
                result = {
                    "content": [{"type": "text", "text": f"Tool error: {exc}"}],
                    "isError": True,
                }
            return {"jsonrpc": "2.0", "id": request_id, "result": result}
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": {"code": -32601, "message": f"method not found: {method}"},
        }
