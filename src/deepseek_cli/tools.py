from __future__ import annotations

import json
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable


class ToolError(RuntimeError):
    """Raised for user-visible tool failures."""


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str

    def to_content(self) -> str:
        status = "ok" if self.ok else "error"
        return json.dumps({"status": status, "output": self.output}, ensure_ascii=False)


def _resolve_workspace_path(cwd: Path, user_path: str) -> Path:
    path = Path(user_path).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def tool_definitions() -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {
                "name": "shell",
                "description": "Run a shell command in the workspace and return stdout/stderr.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string", "description": "Command to run."},
                        "timeout_seconds": {
                            "type": "integer",
                            "description": "Timeout in seconds. Defaults to 60.",
                            "minimum": 1,
                            "maximum": 600,
                        },
                    },
                    "required": ["command"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "read_file",
                "description": "Read a UTF-8 text file from the workspace.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "max_chars": {
                            "type": "integer",
                            "description": "Maximum characters to return. Defaults to 20000.",
                            "minimum": 1,
                        },
                    },
                    "required": ["path"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "write_file",
                "description": "Write a UTF-8 text file, creating parent directories if needed.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "content": {"type": "string"},
                    },
                    "required": ["path", "content"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "replace_in_file",
                "description": "Replace exact text in a UTF-8 text file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "old": {"type": "string"},
                        "new": {"type": "string"},
                        "count": {
                            "type": "integer",
                            "description": "Maximum replacements. Defaults to all occurrences.",
                            "minimum": 1,
                        },
                    },
                    "required": ["path", "old", "new"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "list_dir",
                "description": "List files and directories at a path.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "Directory path. Defaults to '.'."},
                    },
                },
            },
        },
    ]


class ToolExecutor:
    def __init__(
        self,
        cwd: Path,
        *,
        auto_approve: bool = False,
        ask: Callable[[str], bool] | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self.auto_approve = auto_approve
        self.ask = ask or self._default_ask

    def run(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tools: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "shell": self._shell,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "replace_in_file": self._replace_in_file,
            "list_dir": self._list_dir,
        }
        if name not in tools:
            return ToolResult(False, f"Unknown tool: {name}")
        try:
            return tools[name](arguments)
        except Exception as exc:
            return ToolResult(False, str(exc))

    def _default_ask(self, prompt: str) -> bool:
        reply = input(f"{prompt} [y/N] ").strip().lower()
        return reply in {"y", "yes"}

    def _confirm(self, prompt: str) -> None:
        if self.auto_approve:
            return
        if not self.ask(prompt):
            raise ToolError("User rejected tool execution.")

    def _shell(self, arguments: dict[str, Any]) -> ToolResult:
        command = str(arguments["command"])
        timeout = int(arguments.get("timeout_seconds") or 60)
        self._confirm(f"Run shell command: {command}")
        if platform.system() == "Windows":
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=self.cwd,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        else:
            completed = subprocess.run(
                command,
                cwd=self.cwd,
                shell=True,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        output += f"\n[exit_code={completed.returncode}]"
        return ToolResult(completed.returncode == 0, output.strip())

    def _read_file(self, arguments: dict[str, Any]) -> ToolResult:
        path = _resolve_workspace_path(self.cwd, str(arguments["path"]))
        max_chars = int(arguments.get("max_chars") or 20000)
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            content = content[:max_chars] + f"\n[truncated to {max_chars} chars]"
        return ToolResult(True, content)

    def _write_file(self, arguments: dict[str, Any]) -> ToolResult:
        path = _resolve_workspace_path(self.cwd, str(arguments["path"]))
        content = str(arguments["content"])
        self._confirm(f"Write file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
        return ToolResult(True, f"Wrote {path} ({len(content)} chars).")

    def _replace_in_file(self, arguments: dict[str, Any]) -> ToolResult:
        path = _resolve_workspace_path(self.cwd, str(arguments["path"]))
        old = str(arguments["old"])
        new = str(arguments["new"])
        count = arguments.get("count")
        content = path.read_text(encoding="utf-8")
        if old not in content:
            raise ToolError(f"Text not found in {path}.")
        self._confirm(f"Replace text in file: {path}")
        if count is None:
            updated = content.replace(old, new)
        else:
            updated = content.replace(old, new, int(count))
        path.write_text(updated, encoding="utf-8", newline="")
        replacements = content.count(old) if count is None else min(content.count(old), int(count))
        return ToolResult(True, f"Updated {path}; replacements={replacements}.")

    def _list_dir(self, arguments: dict[str, Any]) -> ToolResult:
        path = _resolve_workspace_path(self.cwd, str(arguments.get("path") or "."))
        rows: list[str] = []
        for entry in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            kind = "dir " if entry.is_dir() else "file"
            try:
                size = "" if entry.is_dir() else f" {entry.stat().st_size} bytes"
            except OSError:
                size = ""
            rows.append(f"{kind} {os.path.relpath(entry, self.cwd)}{size}")
        return ToolResult(True, "\n".join(rows) if rows else "(empty)")
