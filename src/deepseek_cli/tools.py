from __future__ import annotations

import json
import os
import platform
import subprocess
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from .policy import PermissionConfig
from .patch_review import HunkDecision, PatchHunk, apply_hunk_decisions, build_hunks
from .tool_installer import resolve_install_plan
from .tools_helpers import (
    ToolError,
    atomic_write,
    apply_unified_patch,
    glob_match,
    read_source,
    resolve_workspace_path,
    truncate_output,
    unified_diff,
)
from .tools_registry import tool_definitions, get_spec, READ_ONLY_TOOLS


# Re-export for backward compatibility (agent.py imports these from .tools)
__all__ = ["ToolError", "ToolResult", "ToolExecutor", "tool_definitions"]


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    output: str

    def to_content(self) -> str:
        status = "ok" if self.ok else "error"
        return json.dumps({"status": status, "output": self.output}, ensure_ascii=False)


# Internal aliases so existing method bodies don't need renaming
_resolve_workspace_path = resolve_workspace_path
_unified_diff = unified_diff
_read_source = read_source
_atomic_write = atomic_write
_truncate_output = truncate_output
_glob_match = glob_match
_apply_unified_patch = apply_unified_patch
_parse_hunks = None  # imported on demand in _patch_file
_fuzzy_match = None  # imported on demand in _patch_file


class ToolExecutor:
    def __init__(
        self,
        cwd: Path,
        *,
        auto_approve: bool = False,
        auto_edit: bool = False,
        ask: Callable[[str], bool] | None = None,
        approve_diff: Callable[[str, str], bool] | None = None,
        approve_file_edits: Callable[[list[tuple[Path, str]]], list[bool]] | None = None,
        approve_hunks: Callable[[list[PatchHunk]], list[HunkDecision]] | None = None,
        policy: PermissionConfig | None = None,
        sandbox: Any | None = None,
    ) -> None:
        self.cwd = cwd.resolve()
        self.policy = policy or PermissionConfig(approval="auto" if auto_approve else "ask")
        self.auto_approve = auto_approve or self.policy.auto_approve
        # auto-edit: auto-approve file edits (write/replace/patch), still ask for shell
        self.auto_edit = auto_edit
        self.ask = ask or self._default_ask
        self.approve_diff = approve_diff
        self.approve_file_edits = approve_file_edits
        self.approve_hunks = approve_hunks
        # OS-level sandbox for shell commands
        self.sandbox = sandbox
        # Checkpoint: track files modified in this session for /undo
        self._modified_files: list[Path] = []
        self._checkpoint_commit: str | None = None
        # Permission memory: tools/commands approved for this session
        self._session_allowed_commands: set[str] = set()
        self._session_allowed_tools: set[str] = set()

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
            "web_search": self._web_search,
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

    def _confirm(self, prompt: str, *, tool_name: str = "", command: str = "") -> None:
        if self.auto_approve:
            return
        # Permission memory: skip confirmation for session-approved tools/commands
        if tool_name and tool_name in self._session_allowed_tools:
            return
        if command and command in self._session_allowed_commands:
            return
        if not self.ask(prompt):
            raise ToolError("User rejected tool execution.")

    def allow_tool_for_session(self, tool_name: str) -> None:
        """Remember that this tool is approved for the rest of the session."""
        self._session_allowed_tools.add(tool_name)

    def allow_command_for_session(self, command: str) -> None:
        """Remember that this command is approved for the rest of the session."""
        self._session_allowed_commands.add(command)

    # ------------------------------------------------------------------
    # Checkpoint / Undo support
    # ------------------------------------------------------------------

    def create_checkpoint(self) -> str | None:
        """Create a git stash checkpoint before file modifications.

        Returns the stash ref (e.g. 'stash@{0}') or None if not in a git repo
        or nothing to stash.
        """
        try:
            result = subprocess.run(
                ["git", "stash", "push", "-u", "-m", "deepseek-cli checkpoint"],
                cwd=self.cwd, text=True, capture_output=True, timeout=30,
            )
            if result.returncode == 0 and "No local changes" not in result.stdout:
                self._checkpoint_commit = "stash@{0}"
                return self._checkpoint_commit
        except (subprocess.TimeoutExpired, OSError, FileNotFoundError):
            pass
        return None

    def undo_checkpoint(self) -> ToolResult:
        """Restore the workspace to the last checkpoint (git stash pop)."""
        if not self._checkpoint_commit:
            return ToolResult(False, "No checkpoint to undo. Checkpoints are created automatically before file edits.")
        try:
            result = subprocess.run(
                ["git", "stash", "pop"],
                cwd=self.cwd, text=True, capture_output=True, timeout=30,
            )
            if result.returncode == 0:
                self._checkpoint_commit = None
                self._modified_files.clear()
                return ToolResult(True, "Undone: workspace restored to last checkpoint.")
            return ToolResult(False, f"git stash pop failed: {result.stderr.strip()}")
        except (subprocess.TimeoutExpired, OSError) as exc:
            return ToolResult(False, f"Undo failed: {exc}")

    def track_modified_file(self, path: Path) -> None:
        """Track a file modified in this session (for /undo and git commit)."""
        if path not in self._modified_files:
            self._modified_files.append(path)

    @property
    def modified_files(self) -> list[Path]:
        """Files modified during this session."""
        return list(self._modified_files)

    def _confirm_diff(self, prompt: str, diff: str) -> None:
        if self.auto_approve or self.auto_edit:
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
        self._confirm(f"Run shell command: {command}", tool_name="shell")

        # Use OS-level sandbox if available
        if self.sandbox and self.sandbox.available:
            result = self.sandbox.run(command, timeout=timeout, cwd=self.cwd)
            output = result.stdout
            if result.stderr:
                output += ("\n" if output else "") + result.stderr
            output += f"\n[exit_code={result.returncode}]"
            if result.sandboxed:
                output += f" [sandbox={result.sandbox_type}]"
            return ToolResult(result.returncode == 0, _truncate_output(output.strip()))

        # Fallback: direct subprocess execution
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
        self.create_checkpoint()
        _atomic_write(path, content)
        self.track_modified_file(path)
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
        self.create_checkpoint()
        _atomic_write(path, updated)
        self.track_modified_file(path)
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
        self.create_checkpoint()
        _atomic_write(path, updated)
        self.track_modified_file(path)
        return ToolResult(True, f"Patched {path} ({len(updated.splitlines())} lines total).")

    def _web_search(self, arguments: dict[str, Any]) -> ToolResult:
        """Search the web using DuckDuckGo HTML (no API key required)."""
        import urllib.request
        import urllib.parse

        query = str(arguments["query"])
        max_results = min(int(arguments.get("max_results") or 5), 10)

        # Use DuckDuckGo lite HTML endpoint (no API key needed)
        url = "https://html.duckduckgo.com/html/?q=" + urllib.parse.quote_plus(query)
        req = urllib.request.Request(url, headers={
            "User-Agent": "Mozilla/5.0 (compatible; DeepSeekCLI/0.9)"
        })
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                html = resp.read().decode("utf-8", errors="replace")
        except Exception as exc:
            return ToolResult(False, f"Web search failed: {exc}")

        # Parse results from DuckDuckGo HTML (simple regex extraction)
        import re
        results = []
        # DuckDuckGo lite returns results in <a class="result__a" href="...">title</a>
        for match in re.finditer(
            r'<a[^>]+class="result__a"[^>]+href="([^"]*)"[^>]*>(.*?)</a>',
            html, re.DOTALL
        ):
            link = match.group(1)
            title = re.sub(r"<[^>]+>", "", match.group(2)).strip()
            # DuckDuckGo wraps URLs in a redirect; extract actual URL
            if "uddg=" in link:
                link = urllib.parse.unquote(link.split("uddg=")[1].split("&")[0])
            results.append({"title": title, "url": link})
            if len(results) >= max_results:
                break

        # Extract snippets
        snippets = re.findall(
            r'<a[^>]+class="result__snippet"[^>]*>(.*?)</a>',
            html, re.DOTALL
        )
        for i, snippet in enumerate(snippets[:len(results)]):
            results[i]["snippet"] = re.sub(r"<[^>]+>", "", snippet).strip()[:200]

        if not results:
            return ToolResult(True, f"No results found for: {query}")

        output_lines = [f"Web search results for: {query}\n"]
        for i, r in enumerate(results, 1):
            output_lines.append(f"{i}. {r['title']}")
            output_lines.append(f"   {r['url']}")
            if r.get("snippet"):
                output_lines.append(f"   {r['snippet']}")
            output_lines.append("")

        return ToolResult(True, "\n".join(output_lines))


