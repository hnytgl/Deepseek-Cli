from __future__ import annotations

import json
import os
import platform
import subprocess
import difflib
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .policy import PermissionConfig
from .patch_review import HunkDecision, PatchHunk, apply_hunk_decisions, build_hunks
from .tool_installer import resolve_install_plan


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


def _unified_diff(path: Path, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
        )
    )


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
                "description": "Read a UTF-8 text file page from the workspace. Use offset/limit to continue large files.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string"},
                        "offset": {
                            "type": "integer",
                            "description": "Character offset to start reading from. Defaults to 0.",
                            "minimum": 0,
                        },
                        "limit": {
                            "type": "integer",
                            "description": "Maximum characters to return. Defaults to 100000.",
                            "minimum": 1,
                        },
                        "max_chars": {
                            "type": "integer",
                            "description": "Deprecated alias for limit.",
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
        {
            "type": "function",
            "function": {
                "name": "apply_file_edits",
                "description": "Apply multi-file full-content edits after per-file diff review.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "files": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "path": {"type": "string"},
                                    "content": {"type": "string"},
                                },
                                "required": ["path", "content"],
                            },
                        }
                    },
                    "required": ["files"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "check_tool",
                "description": "Check whether a local executable is available on PATH.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "install_tool",
                "description": "Install a missing local tool. Automatically chooses an OS-appropriate package manager unless manager/package are provided.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "name": {
                            "type": "string",
                            "description": "Logical tool name, such as ripgrep, jq, git, gh, node.",
                        },
                        "manager": {
                            "type": "string",
                            "description": "Optional override: pip, npm, winget, scoop, choco, brew, apt, dnf, pacman, zypper.",
                        },
                        "package": {"type": "string", "description": "Optional manager-specific package id."},
                    },
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_diff",
                "description": "Show the current multi-file git diff for review.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_status",
                "description": "Show git branch and working tree status.",
                "parameters": {"type": "object", "properties": {}},
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_create_branch",
                "description": "Create and switch to a git branch.",
                "parameters": {
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_commit",
                "description": "Stage selected files and create a git commit.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string"},
                        "files": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Files to stage. Defaults to all changed files.",
                        },
                    },
                    "required": ["message"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "git_create_pr",
                "description": "Push the current branch and create a GitHub pull request using gh.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "title": {"type": "string"},
                        "body": {"type": "string"},
                        "base": {"type": "string", "description": "Base branch. Defaults to repository default."},
                        "draft": {"type": "boolean", "description": "Create a draft PR. Defaults to true."},
                    },
                    "required": ["title", "body"],
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
        approve_diff: Callable[[str, str], bool] | None = None,
        approve_file_edits: Callable[[list[tuple[Path, str]]], list[bool]] | None = None,
        approve_hunks: Callable[[list[PatchHunk]], list[HunkDecision]] | None = None,
        policy: PermissionConfig | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self.policy = policy or PermissionConfig(approval="auto" if auto_approve else "ask")
        self.auto_approve = auto_approve or self.policy.auto_approve
        self.ask = ask or self._default_ask
        self.approve_diff = approve_diff
        self.approve_file_edits = approve_file_edits
        self.approve_hunks = approve_hunks

    def run(self, name: str, arguments: dict[str, Any]) -> ToolResult:
        tools: dict[str, Callable[[dict[str, Any]], ToolResult]] = {
            "shell": self._shell,
            "read_file": self._read_file,
            "write_file": self._write_file,
            "replace_in_file": self._replace_in_file,
            "list_dir": self._list_dir,
            "apply_file_edits": self._apply_file_edits,
            "check_tool": self._check_tool,
            "install_tool": self._install_tool,
            "git_diff": self._git_diff,
            "git_status": self._git_status,
            "git_create_branch": self._git_create_branch,
            "git_commit": self._git_commit,
            "git_create_pr": self._git_create_pr,
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

    def _confirm_diff(self, prompt: str, diff: str) -> None:
        if self.auto_approve:
            return
        if self.approve_diff:
            approved = self.approve_diff(prompt, diff)
        else:
            print(diff)
            approved = self.ask(prompt)
        if not approved:
            raise ToolError("User rejected file change.")

    def _resolve_checked_path(self, user_path: str) -> Path:
        path = _resolve_workspace_path(self.cwd, user_path)
        self.policy.check_path(self.cwd, path)
        return path

    def _shell(self, arguments: dict[str, Any]) -> ToolResult:
        command = str(arguments["command"])
        timeout = int(arguments.get("timeout_seconds") or 60)
        self.policy.check_command(command)
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
        path = self._resolve_checked_path(str(arguments["path"]))
        offset = int(arguments.get("offset") or 0)
        limit = int(arguments.get("limit") or arguments.get("max_chars") or 100000)
        if offset < 0:
            raise ToolError("offset must be >= 0.")
        if limit <= 0:
            raise ToolError("limit must be > 0.")
        content = path.read_text(encoding="utf-8", errors="replace")
        total_chars = len(content)
        page = content[offset : offset + limit]
        end_offset = offset + len(page)
        has_more = end_offset < total_chars
        payload = {
            "path": str(path),
            "offset": offset,
            "limit": limit,
            "end_offset": end_offset,
            "total_chars": total_chars,
            "has_more": has_more,
            "next_offset": end_offset if has_more else None,
            "content": page,
        }
        if has_more:
            payload["instruction"] = (
                "More content is available. Call read_file again with "
                f"offset={end_offset} and limit={limit} to continue."
            )
        return ToolResult(True, json.dumps(payload, ensure_ascii=False))

    def _write_file(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_write()
        path = self._resolve_checked_path(str(arguments["path"]))
        content = str(arguments["content"])
        old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
        diff = _unified_diff(path, old, content)
        self._confirm_diff(f"Apply write to file: {path}", diff or f"Create empty file: {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8", newline="")
        return ToolResult(True, f"Wrote {path} ({len(content)} chars).")

    def _replace_in_file(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_write()
        path = self._resolve_checked_path(str(arguments["path"]))
        old = str(arguments["old"])
        new = str(arguments["new"])
        count = arguments.get("count")
        content = path.read_text(encoding="utf-8")
        if old not in content:
            raise ToolError(f"Text not found in {path}.")
        if count is None:
            updated = content.replace(old, new)
        else:
            updated = content.replace(old, new, int(count))
        self._confirm_diff(f"Apply replacement in file: {path}", _unified_diff(path, content, updated))
        path.write_text(updated, encoding="utf-8", newline="")
        replacements = content.count(old) if count is None else min(content.count(old), int(count))
        return ToolResult(True, f"Updated {path}; replacements={replacements}.")

    def _list_dir(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_checked_path(str(arguments.get("path") or "."))
        rows: list[str] = []
        for entry in sorted(path.iterdir(), key=lambda item: (not item.is_dir(), item.name.lower())):
            kind = "dir " if entry.is_dir() else "file"
            try:
                size = "" if entry.is_dir() else f" {entry.stat().st_size} bytes"
            except OSError:
                size = ""
            rows.append(f"{kind} {os.path.relpath(entry, self.cwd)}{size}")
        return ToolResult(True, "\n".join(rows) if rows else "(empty)")

    def _apply_file_edits(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_write()
        files = arguments.get("files") or []
        planned: list[tuple[Path, str, str, list[PatchHunk]]] = []
        review_items: list[tuple[Path, str]] = []
        all_hunks: list[PatchHunk] = []
        for item in files:
            path = self._resolve_checked_path(str(item["path"]))
            content = str(item["content"])
            old = path.read_text(encoding="utf-8", errors="replace") if path.exists() else ""
            diff = _unified_diff(path, old, content) or f"Create empty file: {path}\n"
            hunks = build_hunks(path, old, content)
            review_items.append((path, diff))
            planned.append((path, old, content, hunks))
            all_hunks.extend(hunks)
        if not planned:
            raise ToolError("No file edits were provided.")
        if self.auto_approve:
            accepted_files = [True for _ in planned]
            accepted_hunks: list[HunkDecision] = [True for _ in all_hunks]
        elif self.approve_hunks and all_hunks:
            accepted_hunks = self.approve_hunks(all_hunks)
            accepted_files = []
            cursor = 0
            for _path, _old, _content, hunks in planned:
                decisions = accepted_hunks[cursor : cursor + len(hunks)]
                accepted_files.append(any(decisions))
                cursor += len(hunks)
        elif self.approve_file_edits:
            accepted_files = self.approve_file_edits(review_items)
            accepted_hunks = []
        else:
            accepted_files = []
            for path, diff in review_items:
                accepted_files.append(self.ask(f"Apply edit for {path}?\n{diff}"))
            accepted_hunks = []
        applied = 0
        rejected = 0
        hunk_cursor = 0
        for accept, (path, old, content, hunks) in zip(accepted_files, planned):
            if accepted_hunks and hunks:
                decisions = accepted_hunks[hunk_cursor : hunk_cursor + len(hunks)]
                hunk_cursor += len(hunks)
                content_to_write = apply_hunk_decisions(old, content, hunks, decisions)
                if content_to_write == old:
                    rejected += 1
                    continue
            else:
                if not accept:
                    rejected += 1
                    continue
                content_to_write = content
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content_to_write, encoding="utf-8", newline="")
            applied += 1
        return ToolResult(applied > 0, f"Applied {applied} file edit(s); rejected={rejected}.")

    def _check_tool(self, arguments: dict[str, Any]) -> ToolResult:
        name = str(arguments["name"])
        executable = shutil.which(name)
        if executable:
            return ToolResult(True, executable)
        return ToolResult(False, f"Tool not found on PATH: {name}")

    def _install_tool(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_install_tools()
        name = str(arguments.get("name") or "") or None
        manager = str(arguments.get("manager") or "") or None
        package = str(arguments.get("package") or "") or None
        plan = resolve_install_plan(tool_name=name, manager=manager, package=package)
        self._confirm(f"Install tool with {plan.manager}: {plan.package}\n{plan.display()}")
        completed = subprocess.run(
            plan.command,
            cwd=self.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=900,
        )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        output += f"\n[exit_code={completed.returncode}]"
        return ToolResult(completed.returncode == 0, output.strip())

    def _run_git(self, args: list[str], *, timeout: int = 120) -> ToolResult:
        completed = subprocess.run(
            ["git", *args],
            cwd=self.cwd,
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

    def _git_status(self, arguments: dict[str, Any]) -> ToolResult:
        _ = arguments
        branch = self._run_git(["branch", "--show-current"])
        status = self._run_git(["status", "--short", "--branch"])
        return ToolResult(branch.ok and status.ok, f"branch={branch.output}\n{status.output}")

    def _git_diff(self, arguments: dict[str, Any]) -> ToolResult:
        _ = arguments
        return self._run_git(["diff", "--", "."])

    def _git_create_branch(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_write()
        name = str(arguments["name"])
        self._confirm(f"Create and switch to git branch: {name}")
        return self._run_git(["switch", "-c", name])

    def _git_commit(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_write()
        message = str(arguments["message"])
        files = [str(item) for item in arguments.get("files") or []]
        self._confirm(f"Stage files and commit: {message}")
        if files:
            for file in files:
                path = self._resolve_checked_path(file)
                result = self._run_git(["add", os.path.relpath(path, self.cwd)])
                if not result.ok:
                    return result
        else:
            result = self._run_git(["add", "-A"])
            if not result.ok:
                return result
        return self._run_git(["commit", "-m", message])

    def _git_create_pr(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_shell()
        title = str(arguments["title"])
        body = str(arguments["body"])
        base = arguments.get("base")
        draft = bool(arguments.get("draft", True))
        self._confirm(f"Push current branch and create GitHub PR: {title}")
        branch = self._run_git(["branch", "--show-current"])
        if not branch.ok:
            return branch
        branch_name = branch.output.splitlines()[0].removeprefix("branch=").strip()
        push = self._run_git(["push", "-u", "origin", branch_name], timeout=300)
        if not push.ok:
            return push
        command = ["gh", "pr", "create", "--title", title, "--body", body]
        if draft:
            command.append("--draft")
        if base:
            command.extend(["--base", str(base)])
        completed = subprocess.run(
            command,
            cwd=self.cwd,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        output += f"\n[exit_code={completed.returncode}]"
        return ToolResult(completed.returncode == 0, output.strip())
