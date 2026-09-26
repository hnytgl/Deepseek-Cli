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


def _read_source(path: Path) -> str:
    """Read a source file preserving original newline style.

    Uses newline='' to prevent universal newline translation, so CRLF files
    on Windows are not silently converted to LF on read/write cycles.
    Raises ToolError on decode failure instead of silently replacing bytes.
    """
    try:
        with open(path, "r", encoding="utf-8", newline="") as f:
            return f.read()
    except UnicodeDecodeError as exc:
        raise ToolError(
            f"Cannot decode {path} as UTF-8 ({exc}). "
            "The file may use a different encoding or be binary."
        ) from exc


def _atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + os.replace.

    Preserves the original file's newline style by using newline=''
    (no translation). If the process is killed mid-write, the original
    file remains intact.
    """
    import tempfile

    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp_path, str(path))
    except BaseException:
        # Clean up temp file on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Maximum characters to keep from shell output (head + tail).
# Prevents OOM and token explosion from commands like `cat big.log`
# or `npm install --verbose`.
_SHELL_OUTPUT_LIMIT = 16384


def _truncate_output(text: str, max_chars: int = _SHELL_OUTPUT_LIMIT) -> str:
    """Truncate large output keeping head and tail for context.

    Returns the original text if within limits, otherwise keeps the first
    and last portions with a truncation marker in between.
    """
    if len(text) <= max_chars:
        return text
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size - 80  # reserve space for marker
    omitted = len(text) - head_size - tail_size
    return (
        text[:head_size]
        + f"\n\n[… truncated {omitted} characters …]\n\n"
        + text[-tail_size:]
    )


def _glob_match(filename: str, pattern: str) -> bool:
    """Simple glob matching for file include filters (e.g. '*.py', 'test_*.py')."""
    import fnmatch
    return fnmatch.fnmatch(filename, pattern)


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
        {
            "type": "function",
            "function": {
                "name": "search",
                "description": (
                    "Search file contents using ripgrep (or built-in fallback). "
                    "Returns matching lines with file paths and line numbers. "
                    "Much faster and cheaper than shell grep."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Regex pattern to search for."},
                        "path": {"type": "string", "description": "Directory or file to search in. Defaults to workspace root."},
                        "include": {"type": "string", "description": "Glob filter for files to include (e.g. '*.py')."},
                        "max_results": {"type": "integer", "description": "Maximum number of matching lines to return. Defaults to 50."},
                    },
                    "required": ["pattern"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "patch_file",
                "description": (
                    "Apply a unified diff patch to a file. Much more token-efficient than "
                    "write_file for small edits — only send the changed lines, not the whole file. "
                    "The patch must be in unified diff format (--- a/file / +++ b/file / @@ hunks @@)."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "path": {"type": "string", "description": "File to patch (relative to workspace)."},
                        "patch": {"type": "string", "description": "Unified diff content to apply."},
                    },
                    "required": ["path", "patch"],
                },
            },
        },
        {
            "type": "function",
            "function": {
                "name": "glob",
                "description": (
                    "Find files matching a glob pattern. Returns relative paths sorted by name. "
                    "Useful for discovering project structure without listing every directory."
                ),
                "parameters": {
                    "type": "object",
                    "properties": {
                        "pattern": {"type": "string", "description": "Glob pattern (e.g. 'src/**/*.py', '*.md')."},
                        "path": {"type": "string", "description": "Base directory. Defaults to workspace root."},
                        "max_results": {"type": "integer", "description": "Maximum files to return. Defaults to 100."},
                    },
                    "required": ["pattern"],
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
            "search": self._search,
            "glob": self._glob,
            "patch_file": self._patch_file,
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
        try:
            timeout = int(arguments.get("timeout_seconds") or 60)
        except (TypeError, ValueError) as exc:
            raise ToolError("timeout_seconds must be an integer between 1 and 600.") from exc
        timeout = max(1, min(timeout, 600))
        self.policy.check_command(command)
        self._confirm(f"Run shell command: {command}")
        if platform.system() == "Windows":
            completed = subprocess.run(
                ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command],
                cwd=self.cwd,
                text=True,
                errors="replace",
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
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        output += f"\n[exit_code={completed.returncode}]"
        # Truncate large outputs to prevent OOM and token explosion.
        # Keep head + tail so the model sees both the start and the error/summary.
        output = _truncate_output(output.strip(), max_chars=16384)
        return ToolResult(completed.returncode == 0, output)

    def _read_file(self, arguments: dict[str, Any]) -> ToolResult:
        path = self._resolve_checked_path(str(arguments["path"]))
        offset = int(arguments.get("offset") or 0)
        limit = int(arguments.get("limit") or arguments.get("max_chars") or 100000)
        if offset < 0:
            raise ToolError("offset must be >= 0.")
        if limit <= 0:
            raise ToolError("limit must be > 0.")
        file_size = path.stat().st_size
        with path.open("rb") as binary:
            sample = binary.read(4096)
        if b"\x00" in sample:
            raise ToolError(
                f"File appears to be binary ({file_size} bytes). read_file only supports UTF-8 text files."
            )

        page_parts: list[str] = []
        skipped = 0
        collected = 0
        has_more = False
        with path.open("r", encoding="utf-8", errors="replace", newline="") as stream:
            while chunk := stream.read(65536):
                if skipped + len(chunk) <= offset:
                    skipped += len(chunk)
                    continue
                start = max(0, offset - skipped)
                available = chunk[start:]
                needed = limit - collected
                page_parts.append(available[:needed])
                collected += min(len(available), needed)
                skipped += len(chunk)
                if len(available) > needed:
                    has_more = True
                    break
                if collected >= limit:
                    has_more = bool(stream.read(1))
                    break
        page = "".join(page_parts)
        end_offset = offset + len(page)
        payload = {
            "path": str(path),
            "offset": offset,
            "limit": limit,
            "end_offset": end_offset,
            "file_size_bytes": file_size,
            "has_more": has_more,
            "next_offset": end_offset if has_more else None,
            "content": page,
        }
        if file_size > 10 * 1024 * 1024:
            payload["warning"] = "Large file detected; continue reading in bounded pages."
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
        old = _read_source(path) if path.exists() else ""
        diff = _unified_diff(path, old, content)
        self._confirm_diff(f"Apply write to file: {path}", diff or f"Create empty file: {path}")
        _atomic_write(path, content)
        return ToolResult(True, f"Wrote {path} ({len(content)} chars).")

    def _replace_in_file(self, arguments: dict[str, Any]) -> ToolResult:
        self.policy.check_write()
        path = self._resolve_checked_path(str(arguments["path"]))
        old = str(arguments["old"])
        new = str(arguments["new"])
        if not old:
            raise ToolError("'old' must not be empty. Use write_file to replace entire content.")
        count = arguments.get("count")
        content = _read_source(path)
        if old not in content:
            raise ToolError(f"Text not found in {path}.")
        if count is None:
            updated = content.replace(old, new)
        else:
            updated = content.replace(old, new, int(count))
        self._confirm_diff(f"Apply replacement in file: {path}", _unified_diff(path, content, updated))
        _atomic_write(path, updated)
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
            # Use universal newlines for diff/hunk comparison since model content
            # is always LF. The write path uses _atomic_write which preserves
            # whatever newline style is in the final content.
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
            _atomic_write(path, content_to_write)
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
            errors="replace",
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
            errors="replace",
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
                result = self._run_git(["add", "--", os.path.relpath(path, self.cwd)])
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
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=120,
        )
        output = completed.stdout
        if completed.stderr:
            output += ("\n" if output else "") + completed.stderr
        output += f"\n[exit_code={completed.returncode}]"
        return ToolResult(completed.returncode == 0, output.strip())

    # ------------------------------------------------------------------
    # Search tools (grep/glob) — no shell required, no policy escalation
    # ------------------------------------------------------------------

    def _search(self, arguments: dict[str, Any]) -> ToolResult:
        """Search file contents using ripgrep (preferred) or built-in Python fallback."""
        import re as _re

        pattern = str(arguments["pattern"])
        search_path = self._resolve_checked_path(str(arguments.get("path") or "."))
        include = arguments.get("include")  # glob filter like "*.py"
        max_results = min(int(arguments.get("max_results") or 50), 200)

        # Try ripgrep first (fast, respects .gitignore)
        rg = shutil.which("rg")
        if rg:
            cmd = [rg, "--no-heading", "--line-number", "--max-count", str(max_results), pattern]
            if include:
                cmd.extend(["--glob", str(include)])
            cmd.append(str(search_path))
            try:
                completed = subprocess.run(
                    cmd, cwd=self.cwd, text=True, errors="replace",
                    stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30,
                )
                if completed.returncode in (0, 1):  # 1 = no matches
                    output = completed.stdout.strip() or "(no matches)"
                    return ToolResult(True, _truncate_output(output, 8192))
            except (subprocess.TimeoutExpired, OSError):
                pass  # fall through to Python fallback

        # Python fallback: walk directory and regex match
        try:
            regex = _re.compile(pattern)
        except _re.error as exc:
            raise ToolError(f"Invalid regex pattern: {exc}") from exc

        results: list[str] = []
        files_scanned = 0
        for root, dirs, files in os.walk(search_path):
            # Skip hidden dirs and common noise
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in
                       ("node_modules", "__pycache__", ".git", "venv", ".venv", "dist", "build")]
            for fname in sorted(files):
                if include and not _glob_match(fname, str(include)):
                    continue
                fpath = Path(root) / fname
                if fpath.is_symlink():
                    continue
                try:
                    text = fpath.read_text(encoding="utf-8", errors="ignore")
                except (OSError, ValueError):
                    continue
                files_scanned += 1
                for lineno, line in enumerate(text.splitlines(), 1):
                    if regex.search(line):
                        rel = os.path.relpath(fpath, self.cwd)
                        results.append(f"{rel}:{lineno}:{line.rstrip()}")
                        if len(results) >= max_results:
                            break
                if len(results) >= max_results:
                    break
            if len(results) >= max_results:
                break

        if not results:
            return ToolResult(True, f"(no matches in {files_scanned} files scanned)")
        header = f"Found {len(results)} match(es) in {files_scanned} files scanned:\n"
        return ToolResult(True, _truncate_output(header + "\n".join(results), 8192))

    def _glob(self, arguments: dict[str, Any]) -> ToolResult:
        """Find files matching a glob pattern."""
        pattern = str(arguments["pattern"])
        base_path = self._resolve_checked_path(str(arguments.get("path") or "."))
        max_results = min(int(arguments.get("max_results") or 100), 500)

        matches: list[str] = []
        try:
            for match in sorted(base_path.glob(pattern)):
                if match.is_file():
                    matches.append(os.path.relpath(match, self.cwd))
                    if len(matches) >= max_results:
                        break
        except (OSError, ValueError) as exc:
            raise ToolError(f"Glob error: {exc}") from exc

        if not matches:
            return ToolResult(True, f"(no files matching '{pattern}')")
        header = f"Found {len(matches)} file(s):\n"
        return ToolResult(True, header + "\n".join(matches))

    def _patch_file(self, arguments: dict[str, Any]) -> ToolResult:
        """Apply a unified diff patch to a file.

        Much more token-efficient than write_file for small edits — the model
        only sends the changed lines, not the entire file content.
        """
        self.policy.check_write()
        path = self._resolve_checked_path(str(arguments["path"]))
        patch_text = str(arguments["patch"])

        if not patch_text.strip():
            raise ToolError("Patch content must not be empty.")

        original = _read_source(path) if path.exists() else ""
        updated = _apply_unified_patch(original, patch_text)

        if updated == original:
            return ToolResult(False, f"Patch produced no changes to {path}. Check that context lines match exactly.")

        diff = _unified_diff(path, original, updated)
        self._confirm_diff(f"Apply patch to file: {path}", diff)
        _atomic_write(path, updated)
        # Count changed lines for feedback
        added = sum(1 for line in updated.splitlines() if line not in original.splitlines())
        return ToolResult(True, f"Patched {path} ({len(updated.splitlines())} lines total).")


def _apply_unified_patch(original: str, patch_text: str) -> str:
    """Apply a unified diff patch to original text.

    Supports standard unified diff format:
        --- a/file
        +++ b/file
        @@ -start,count +start,count @@
        -removed line
        +added line
         context line

    Falls back to simple line-based hunk application if header parsing fails.
    """
    lines = original.splitlines(keepends=True)
    # Ensure last line has newline for consistent processing
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
        trailing_newline = False
    else:
        trailing_newline = True

    result = list(lines)
    hunks = _parse_hunks(patch_text)

    if not hunks:
        raise ToolError("No valid hunks found in patch. Expected @@ -N,M +N,M @@ headers.")

    # Apply hunks in reverse order to preserve line numbers
    offset = 0
    for hunk in sorted(hunks, key=lambda h: h["orig_start"], reverse=True):
        start = hunk["orig_start"] - 1  # 0-indexed
        orig_lines = hunk["orig_lines"]
        new_lines = hunk["new_lines"]

        # Verify context matches
        actual = result[start:start + len(orig_lines)]
        if not _fuzzy_match(actual, orig_lines):
            raise ToolError(
                f"Patch hunk at line {hunk['orig_start']} does not match file content. "
                "The file may have been modified since the patch was generated."
            )

        result[start:start + len(orig_lines)] = new_lines

    patched = "".join(result)
    if not trailing_newline and patched.endswith("\n"):
        patched = patched[:-1]
    return patched


def _parse_hunks(patch_text: str) -> list[dict[str, Any]]:
    """Parse unified diff into hunks."""
    import re as _re

    hunks = []
    hunk_header = _re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    current_hunk = None

    for line in patch_text.splitlines(keepends=True):
        match = hunk_header.match(line)
        if match:
            if current_hunk:
                hunks.append(current_hunk)
            current_hunk = {
                "orig_start": int(match.group(1)),
                "orig_count": int(match.group(2) or 1),
                "new_start": int(match.group(3)),
                "new_count": int(match.group(4) or 1),
                "orig_lines": [],
                "new_lines": [],
            }
            continue

        if current_hunk is None:
            continue  # skip --- / +++ headers

        # Ensure line ends with \n for consistent comparison
        if not line.endswith("\n"):
            line += "\n"

        if line.startswith("-"):
            current_hunk["orig_lines"].append(line[1:])
        elif line.startswith("+"):
            current_hunk["new_lines"].append(line[1:])
        elif line.startswith(" ") or line == "\n":
            content = line[1:] if line.startswith(" ") else line
            current_hunk["orig_lines"].append(content)
            current_hunk["new_lines"].append(content)
        elif line.startswith("\\"):
            continue  # "\ No newline at end of file"
        # else: unknown line, skip

    if current_hunk:
        hunks.append(current_hunk)
    return hunks


def _fuzzy_match(actual: list[str], expected: list[str]) -> bool:
    """Check if actual lines match expected, ignoring trailing whitespace differences."""
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        if a.rstrip("\r\n") != e.rstrip("\r\n"):
            return False
    return True
