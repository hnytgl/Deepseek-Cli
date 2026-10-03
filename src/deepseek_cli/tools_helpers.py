"""
deepseek_cli.tools_helpers -- Shared utilities for tool implementations.

Extracted from tools.py to reduce monolith size and enable independent testing.
"""

from __future__ import annotations

import difflib
import fnmatch
import os
import re
import tempfile
from pathlib import Path
from typing import Any


class ToolError(RuntimeError):
    """Raised for user-visible tool failures."""


def resolve_workspace_path(cwd: Path, user_path: str) -> Path:
    path = Path(user_path).expanduser()
    if not path.is_absolute():
        path = cwd / path
    return path.resolve()


def unified_diff(path: Path, old: str, new: str) -> str:
    return "".join(
        difflib.unified_diff(
            old.splitlines(keepends=True),
            new.splitlines(keepends=True),
            fromfile=f"a/{path.name}",
            tofile=f"b/{path.name}",
        )
    )


def read_source(path: Path) -> str:
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


def preserve_newlines(original: str, content: str) -> str:
    """Preserve a uniformly CRLF source when model edits arrive as LF."""
    if "\r\n" in original and "\n" not in original.replace("\r\n", ""):
        return content.replace("\r\n", "\n").replace("\n", "\r\n")
    return content


def atomic_write(path: Path, content: str) -> None:
    """Write content to path atomically via temp file + os.replace.

    Preserves the original file's newline style by using newline=''
    (no translation). If the process is killed mid-write, the original
    file remains intact.
    """
    if path.exists():
        content = preserve_newlines(read_source(path), content)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(path.parent), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as f:
            f.write(content)
        os.replace(tmp_path, str(path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


# Maximum characters to keep from shell output (head + tail).
SHELL_OUTPUT_LIMIT = 16384


def truncate_output(text: str, max_chars: int = SHELL_OUTPUT_LIMIT) -> str:
    """Truncate large output keeping head and tail for context."""
    if len(text) <= max_chars:
        return text
    head_size = max_chars * 2 // 3
    tail_size = max_chars - head_size - 80
    omitted = len(text) - head_size - tail_size
    return (
        text[:head_size]
        + f"\n\n[… truncated {omitted} characters …]\n\n"
        + text[-tail_size:]
    )


def glob_match(filename: str, pattern: str) -> bool:
    """Simple glob matching for file include filters."""
    return fnmatch.fnmatch(filename, pattern)


# ---------------------------------------------------------------------------
# Unified diff patch engine
# ---------------------------------------------------------------------------

def apply_unified_patch(original: str, patch_text: str) -> str:
    """Apply a unified diff patch to original text."""
    lines = original.replace("\r\n", "\n").splitlines(keepends=True)
    if lines and not lines[-1].endswith("\n"):
        lines[-1] += "\n"
        trailing_newline = False
    else:
        trailing_newline = True

    result = list(lines)
    hunks = parse_hunks(patch_text)

    if not hunks:
        raise ToolError("No valid hunks found in patch. Expected @@ -N,M +N,M @@ headers.")

    for hunk in sorted(hunks, key=lambda h: h["orig_start"], reverse=True):
        start = hunk["orig_start"] if hunk["orig_count"] == 0 else hunk["orig_start"] - 1
        orig_lines = hunk["orig_lines"]
        new_lines = hunk["new_lines"]
        if len(orig_lines) != hunk["orig_count"] or len(new_lines) != hunk["new_count"]:
            raise ToolError("Patch hunk line counts do not match its header.")
        if start < 0 or start > len(result):
            raise ToolError("Patch hunk starts outside the file.")

        actual = result[start:start + len(orig_lines)]
        if not fuzzy_match(actual, orig_lines):
            raise ToolError(
                f"Patch hunk at line {hunk['orig_start']} does not match file content. "
                "The file may have been modified since the patch was generated."
            )

        result[start:start + len(orig_lines)] = new_lines

    patched = "".join(result)
    if not trailing_newline and patched.endswith("\n"):
        patched = patched[:-1]
    return preserve_newlines(original, patched)


def parse_hunks(patch_text: str) -> list[dict[str, Any]]:
    """Parse unified diff into hunks."""
    hunks: list[dict[str, Any]] = []
    hunk_header = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")
    current_hunk: dict[str, Any] | None = None

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
            continue

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
            continue

    if current_hunk:
        hunks.append(current_hunk)
    return hunks


def fuzzy_match(actual: list[str], expected: list[str]) -> bool:
    """Check if actual lines match expected, ignoring trailing whitespace."""
    if len(actual) != len(expected):
        return False
    for a, e in zip(actual, expected):
        if a.rstrip("\r\n") != e.rstrip("\r\n"):
            return False
    return True
