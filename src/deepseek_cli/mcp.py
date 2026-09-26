"""
deepseek_cli.mcp -- Minimal MCP (Model Context Protocol) client.

Supports connecting to MCP servers configured in config.toml:

    [mcp_servers.filesystem]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-filesystem", "/path/to/dir"]

    [mcp_servers.github]
    command = "npx"
    args = ["-y", "@modelcontextprotocol/server-github"]
    env = { GITHUB_TOKEN = "ghp_..." }

The client spawns MCP servers as subprocesses, communicates via JSON-RPC
over stdin/stdout, and exposes their tools alongside built-in tools.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from typing import Any


@dataclass
class MCPTool:
    """A tool exposed by an MCP server."""
    name: str
    description: str
    input_schema: dict[str, Any]
    server_name: str


@dataclass
class MCPServer:
    """A running MCP server subprocess."""
    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    process: subprocess.Popen | None = None
    tools: list[MCPTool] = field(default_factory=list)
    _request_id: int = field(default=0, init=False)

    def start(self) -> bool:
        """Start the MCP server subprocess and initialize."""
        try:
            full_env = {**os.environ, **self.env}
            self.process = subprocess.Popen(
                [self.command] + self.args,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                env=full_env,
                text=True,
            )
            # Send initialize request
            result = self._send_request("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "deepseek-cli", "version": "0.9.0"},
            })
            if result is None:
                return False
            # Send initialized notification
            self._send_notification("notifications/initialized", {})
            return True
        except (OSError, FileNotFoundError):
            return False

    def list_tools(self) -> list[MCPTool]:
        """Request the list of tools from the server."""
        result = self._send_request("tools/list", {})
        if not result or "tools" not in result:
            return []
        self.tools = []
        for tool in result["tools"]:
            self.tools.append(MCPTool(
                name=tool.get("name", ""),
                description=tool.get("description", ""),
                input_schema=tool.get("inputSchema", {}),
                server_name=self.name,
            ))
        return self.tools

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> dict[str, Any] | None:
        """Call a tool on the MCP server."""
        return self._send_request("tools/call", {
            "name": tool_name,
            "arguments": arguments,
        })

    def stop(self) -> None:
        """Terminate the server subprocess."""
        if self.process and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
        self.process = None

    def _send_request(self, method: str, params: dict[str, Any]) -> dict[str, Any] | None:
        """Send a JSON-RPC request and wait for response."""
        if not self.process or self.process.poll() is not None:
            return None
        self._request_id += 1
        request = {
            "jsonrpc": "2.0",
            "id": self._request_id,
            "method": method,
            "params": params,
        }
        try:
            line = json.dumps(request) + "\n"
            self.process.stdin.write(line)  # type: ignore[union-attr]
            self.process.stdin.flush()  # type: ignore[union-attr]
            # Read response (single line JSON)
            response_line = self.process.stdout.readline()  # type: ignore[union-attr]
            if not response_line:
                return None
            response = json.loads(response_line)
            if "error" in response:
                return None
            return response.get("result")
        except (BrokenPipeError, OSError, json.JSONDecodeError):
            return None

    def _send_notification(self, method: str, params: dict[str, Any]) -> None:
        """Send a JSON-RPC notification (no response expected)."""
        if not self.process or self.process.poll() is not None:
            return
        notification = {
            "jsonrpc": "2.0",
            "method": method,
            "params": params,
        }
        try:
            self.process.stdin.write(json.dumps(notification) + "\n")  # type: ignore[union-attr]
            self.process.stdin.flush()  # type: ignore[union-attr]
        except (BrokenPipeError, OSError):
            pass


class MCPClient:
    """
    Manages multiple MCP server connections.

    Loads server configs from AppConfig.mcp_servers, starts them,
    and provides a unified tool interface.
    """

    def __init__(self) -> None:
        self.servers: dict[str, MCPServer] = {}
        self._tools: dict[str, MCPTool] = {}  # tool_name -> MCPTool

    def load_from_config(self, mcp_servers: dict[str, dict[str, Any]]) -> None:
        """Load MCP server definitions from config."""
        for name, server_config in mcp_servers.items():
            command = server_config.get("command", "")
            if not command:
                continue
            args = server_config.get("args", [])
            env = server_config.get("env", {})
            self.servers[name] = MCPServer(
                name=name,
                command=command,
                args=[str(a) for a in args],
                env={str(k): str(v) for k, v in env.items()},
            )

    def start_all(self) -> list[str]:
        """Start all configured servers. Returns list of successfully started server names."""
        started = []
        for name, server in self.servers.items():
            if server.start():
                tools = server.list_tools()
                for tool in tools:
                    # Prefix with server name to avoid collisions
                    qualified_name = f"mcp_{name}_{tool.name}"
                    self._tools[qualified_name] = MCPTool(
                        name=qualified_name,
                        description=f"[MCP:{name}] {tool.description}",
                        input_schema=tool.input_schema,
                        server_name=name,
                    )
                started.append(name)
        return started

    def stop_all(self) -> None:
        """Stop all running servers."""
        for server in self.servers.values():
            server.stop()

    @property
    def tools(self) -> dict[str, MCPTool]:
        """All available MCP tools (qualified names)."""
        return dict(self._tools)

    def tool_definitions(self) -> list[dict[str, Any]]:
        """Generate OpenAI-compatible tool definitions for MCP tools."""
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description,
                    "parameters": tool.input_schema,
                },
            }
            for tool in self._tools.values()
        ]

    def call_tool(self, qualified_name: str, arguments: dict[str, Any]) -> str:
        """Call an MCP tool by qualified name. Returns result as string."""
        tool = self._tools.get(qualified_name)
        if not tool:
            return json.dumps({"error": f"Unknown MCP tool: {qualified_name}"})
        server = self.servers.get(tool.server_name)
        if not server:
            return json.dumps({"error": f"MCP server not running: {tool.server_name}"})
        # Strip the prefix to get the original tool name
        original_name = qualified_name.removeprefix(f"mcp_{tool.server_name}_")
        result = server.call_tool(original_name, arguments)
        if result is None:
            return json.dumps({"error": "MCP tool call failed or timed out"})
        # Extract content from MCP response
        content = result.get("content", [])
        if isinstance(content, list):
            texts = [c.get("text", "") for c in content if c.get("type") == "text"]
            return "\n".join(texts) if texts else json.dumps(result, ensure_ascii=False)
        return json.dumps(result, ensure_ascii=False)

    @property
    def available(self) -> bool:
        """Whether any MCP servers are connected."""
        return bool(self._tools)
