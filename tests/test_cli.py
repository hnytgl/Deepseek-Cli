from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_cli.api import DeepSeekAPIError
from deepseek_cli.cli import build_parser, main, resolve_cwd


def test_resolve_cwd_defaults_to_launch_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_cwd(None) == tmp_path.resolve()


def test_resolve_cwd_uses_explicit_directory(tmp_path: Path) -> None:
    child = tmp_path / "project"
    child.mkdir()

    assert resolve_cwd(str(child)) == child.resolve()


@pytest.mark.parametrize("option", ["--max-steps", "--max-context-chars"])
def test_positive_cli_limits(option: str) -> None:
    parser = build_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([option, "0"])


def test_one_shot_api_error_is_user_friendly(monkeypatch, capsys) -> None:
    class FailingAgent:
        events = None

        def run_turn(self, prompt: str) -> str:
            _ = prompt
            raise DeepSeekAPIError("request failed")

    monkeypatch.setattr("deepseek_cli.cli.create_agent", lambda _args: FailingAgent())

    assert main(["--plain", "hello"]) == 2
    assert "Error: request failed" in capsys.readouterr().err


def test_show_policy_error_is_user_friendly(tmp_path: Path, capsys) -> None:
    policy_path = tmp_path / ".deepseek-cli" / "policy.json"
    policy_path.parent.mkdir()
    policy_path.write_text("{", encoding="utf-8")

    assert main(["--cwd", str(tmp_path), "--show-policy"]) == 2
    assert "Error: Could not read policy file" in capsys.readouterr().err
