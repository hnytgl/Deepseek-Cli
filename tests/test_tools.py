from __future__ import annotations

from pathlib import Path

from deepseek_cli.tools import ToolExecutor


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
