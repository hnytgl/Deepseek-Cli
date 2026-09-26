"""
deepseek_cli.tools_registry -- Data-driven tool definitions.

Replaces the 220-line JSON literal in tools.py with a declarative registry.
Adding a new tool requires only appending a ToolSpec here + implementing the
handler method in ToolExecutor. Definitions are auto-generated for the API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolSpec:
    """Declaration of a single tool's schema and behavior flags."""
    name: str
    description: str
    parameters: dict[str, Any]
    read_only: bool = False       # Can be executed concurrently
    needs_confirm: bool = True    # Skipped in auto-edit mode for file edits
    needs_shell: bool = False     # Blocked by --no-shell


# ---------------------------------------------------------------------------
# Tool registry — single source of truth for definitions + dispatch metadata
# ---------------------------------------------------------------------------

REGISTRY: list[ToolSpec] = [
    ToolSpec(
        name="shell",
        description="Run a shell command in the workspace and return stdout/stderr.",
        parameters={
            "type": "object",
            "properties": {
                "command": {"type": "string", "description": "Command to run."},
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout in seconds. Defaults to 60.",
                    "minimum": 1, "maximum": 600,
                },
            },
            "required": ["command"],
        },
        needs_shell=True,
    ),
    ToolSpec(
        name="read_file",
        description="Read a UTF-8 text file page from the workspace. Use offset/limit to continue large files.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "offset": {"type": "integer", "description": "Character offset to start reading from."},
                "limit": {"type": "integer", "description": "Max characters to return. Defaults to 100000."},
            },
            "required": ["path"],
        },
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="write_file",
        description="Write content to a file, creating parent directories as needed.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    ),
    ToolSpec(
        name="replace_in_file",
        description="Replace exact text in a file. Provide old text and new text.",
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old": {"type": "string", "description": "Exact text to find (must not be empty)."},
                "new": {"type": "string", "description": "Replacement text."},
                "count": {"type": "integer", "description": "Max replacements. Defaults to all."},
            },
            "required": ["path", "old", "new"],
        },
    ),
    ToolSpec(
        name="patch_file",
        description=(
            "Apply a unified diff patch to a file. Much more token-efficient than "
            "write_file for small edits — only send the changed lines, not the whole file."
        ),
        parameters={
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File to patch (relative to workspace)."},
                "patch": {"type": "string", "description": "Unified diff content to apply."},
            },
            "required": ["path", "patch"],
        },
    ),
    ToolSpec(
        name="list_dir",
        description="List directory contents with file sizes.",
        parameters={
            "type": "object",
            "properties": {"path": {"type": "string", "description": "Directory path. Defaults to workspace root."}},
        },
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="search",
        description=(
            "Search file contents using ripgrep (or built-in fallback). "
            "Returns matching lines with file paths and line numbers."
        ),
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Regex pattern to search for."},
                "path": {"type": "string", "description": "Directory or file to search in."},
                "include": {"type": "string", "description": "Glob filter (e.g. '*.py')."},
                "max_results": {"type": "integer", "description": "Max matching lines. Defaults to 50."},
            },
            "required": ["pattern"],
        },
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="glob",
        description="Find files matching a glob pattern. Returns relative paths sorted by name.",
        parameters={
            "type": "object",
            "properties": {
                "pattern": {"type": "string", "description": "Glob pattern (e.g. 'src/**/*.py')."},
                "path": {"type": "string", "description": "Base directory."},
                "max_results": {"type": "integer", "description": "Max files to return. Defaults to 100."},
            },
            "required": ["pattern"],
        },
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="apply_file_edits",
        description="Apply multiple file edits at once with hunk-level review.",
        parameters={
            "type": "object",
            "properties": {
                "files": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {"type": "string"},
                            "content": {"type": "string", "description": "Full new file content."},
                        },
                        "required": ["path", "content"],
                    },
                },
            },
            "required": ["files"],
        },
    ),
    ToolSpec(
        name="check_tool",
        description="Check if a command-line tool is available on this system.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="install_tool",
        description="Install a missing command-line tool using the system package manager.",
        parameters={
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Tool name (e.g. ripgrep, jq, git)."},
                "manager": {"type": "string", "description": "Package manager override (e.g. brew, pip, winget)."},
                "package": {"type": "string", "description": "Package name override."},
            },
            "required": ["name"],
        },
        needs_shell=True,
    ),
    ToolSpec(
        name="git_diff",
        description="Show the current git diff for the workspace.",
        parameters={"type": "object", "properties": {}},
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="git_status",
        description="Show git branch and working tree status.",
        parameters={"type": "object", "properties": {}},
        read_only=True,
        needs_confirm=False,
    ),
    ToolSpec(
        name="git_create_branch",
        description="Create and switch to a git branch.",
        parameters={
            "type": "object",
            "properties": {"name": {"type": "string"}},
            "required": ["name"],
        },
        needs_shell=True,
    ),
    ToolSpec(
        name="git_commit",
        description="Stage selected files and create a git commit.",
        parameters={
            "type": "object",
            "properties": {
                "message": {"type": "string"},
                "files": {"type": "array", "items": {"type": "string"}, "description": "Files to stage. Defaults to all."},
            },
            "required": ["message"],
        },
        needs_shell=True,
    ),
    ToolSpec(
        name="git_create_pr",
        description="Push the current branch and create a GitHub pull request using gh.",
        parameters={
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "body": {"type": "string"},
                "base": {"type": "string", "description": "Base branch."},
                "draft": {"type": "boolean", "description": "Create a draft PR. Defaults to true."},
            },
            "required": ["title", "body"],
        },
        needs_shell=True,
    ),
    ToolSpec(
        name="web_search",
        description=(
            "Search the web for current information. Returns top results with titles, "
            "URLs and snippets. Useful for looking up documentation, APIs, error messages."
        ),
        parameters={
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query."},
                "max_results": {"type": "integer", "description": "Max results to return. Defaults to 5."},
            },
            "required": ["query"],
        },
        read_only=True,
        needs_confirm=False,
    ),
]

# Lookup tables built from registry
_BY_NAME: dict[str, ToolSpec] = {spec.name: spec for spec in REGISTRY}
READ_ONLY_TOOLS: frozenset[str] = frozenset(s.name for s in REGISTRY if s.read_only)
SHELL_TOOLS: frozenset[str] = frozenset(s.name for s in REGISTRY if s.needs_shell)


def get_spec(name: str) -> ToolSpec | None:
    return _BY_NAME.get(name)


def tool_definitions() -> list[dict[str, Any]]:
    """Generate OpenAI-compatible tool definitions from the registry."""
    return [
        {
            "type": "function",
            "function": {
                "name": spec.name,
                "description": spec.description,
                "parameters": spec.parameters,
            },
        }
        for spec in REGISTRY
    ]


def tool_names() -> list[str]:
    return [spec.name for spec in REGISTRY]
