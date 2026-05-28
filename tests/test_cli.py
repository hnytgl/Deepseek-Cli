from __future__ import annotations

from pathlib import Path

from deepseek_cli.cli import resolve_cwd


def test_resolve_cwd_defaults_to_launch_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_cwd(None) == tmp_path.resolve()


def test_resolve_cwd_uses_explicit_directory(tmp_path: Path) -> None:
    child = tmp_path / "project"
    child.mkdir()

    assert resolve_cwd(str(child)) == child.resolve()
