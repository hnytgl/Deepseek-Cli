from __future__ import annotations

from deepseek_cli.policy import command_name


def test_command_name_extracts_executable() -> None:
    assert command_name("python -m pytest") == "python"
    assert command_name('"C:\\Program Files\\Git\\bin\\git.exe" status') == "git.exe"
