from __future__ import annotations

from pathlib import Path

from deepseek_cli.tools import ToolExecutor
from deepseek_cli.policy import PermissionConfig


def test_write_read_and_replace_file(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path, auto_approve=True)

    write = executor.run("write_file", {"path": "demo.txt", "content": "hello codex"})
    assert write.ok

    read = executor.run("read_file", {"path": "demo.txt"})
    assert read.ok
    assert read.output == "hello codex"

    replace = executor.run("replace_in_file", {"path": "demo.txt", "old": "codex", "new": "deepseek"})
    assert replace.ok

    assert (tmp_path / "demo.txt").read_text(encoding="utf-8") == "hello deepseek"


def test_shell_returns_exit_code(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path, auto_approve=True)
    result = executor.run("shell", {"command": "python --version"})
    assert result.ok
    assert "[exit_code=0]" in result.output


def test_write_file_uses_diff_approval(tmp_path: Path) -> None:
    diffs: list[str] = []
    executor = ToolExecutor(
        tmp_path,
        approve_diff=lambda _prompt, diff: diffs.append(diff) or True,
    )

    result = executor.run("write_file", {"path": "demo.txt", "content": "hello"})

    assert result.ok
    assert "+hello" in diffs[0]


def test_workspace_sandbox_blocks_path_escape(tmp_path: Path) -> None:
    executor = ToolExecutor(tmp_path, auto_approve=True, policy=PermissionConfig(sandbox="workspace"))

    result = executor.run("read_file", {"path": "../outside.txt"})

    assert not result.ok
    assert "outside workspace sandbox" in result.output


def test_shell_command_allowlist(tmp_path: Path) -> None:
    executor = ToolExecutor(
        tmp_path,
        auto_approve=True,
        policy=PermissionConfig(approval="auto", allow_commands=("python",)),
    )

    ok = executor.run("shell", {"command": "python --version"})
    blocked = executor.run("shell", {"command": "git --version"})

    assert ok.ok
    assert not blocked.ok
    assert "not in allowlist" in blocked.output


def test_shell_command_denylist(tmp_path: Path) -> None:
    executor = ToolExecutor(
        tmp_path,
        auto_approve=True,
        policy=PermissionConfig(approval="auto", deny_commands=("git",)),
    )

    result = executor.run("shell", {"command": "git --version"})

    assert not result.ok
    assert "blocked by policy" in result.output


def test_apply_file_edits_reviews_combined_diff(tmp_path: Path) -> None:
    diffs: list[str] = []
    executor = ToolExecutor(
        tmp_path,
        approve_diff=lambda _prompt, diff: diffs.append(diff) or True,
    )

    result = executor.run(
        "apply_file_edits",
        {
            "files": [
                {"path": "a.txt", "content": "A"},
                {"path": "nested/b.txt", "content": "B"},
            ]
        },
    )

    assert result.ok
    assert (tmp_path / "a.txt").read_text(encoding="utf-8") == "A"
    assert (tmp_path / "nested" / "b.txt").read_text(encoding="utf-8") == "B"
    assert "+A" in diffs[0]
    assert "+B" in diffs[0]
