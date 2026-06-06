from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_cli.api import DeepSeekAPIError
from deepseek_cli.cli import build_parser, format_sessions, main, resolve_cwd
from deepseek_cli.session import SessionStore


def test_resolve_cwd_defaults_to_launch_directory(monkeypatch, tmp_path: Path) -> None:
    monkeypatch.chdir(tmp_path)

    assert resolve_cwd(None) == tmp_path.resolve()


def test_resolve_cwd_uses_explicit_directory(tmp_path: Path) -> None:
    child = tmp_path / "project"
    child.mkdir()

    assert resolve_cwd(str(child)) == child.resolve()


@pytest.mark.parametrize("option", ["--max-steps", "--max-context-chars", "--api-timeout"])
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


def test_format_sessions_includes_preview(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.save(
        "demo",
        [{"role": "user", "content": "Workspace: x\n\nfix the parser"}],
        cwd=tmp_path,
        model="deepseek-chat",
    )

    output = format_sessions(store, "parser")

    assert "demo" in output
    assert "fix the parser" in output


def test_parser_accepts_theme_and_session_commands() -> None:
    args = build_parser().parse_args(["--theme", "ocean", "--sessions", "parser"])

    assert args.theme == "ocean"
    assert args.sessions == "parser"


def test_parser_accepts_api_retry_and_sensitive_session_options() -> None:
    args = build_parser().parse_args(["--api-timeout", "30.5", "--api-retries", "5", "--save-sensitive"])

    assert args.api_timeout == 30.5
    assert args.api_retries == 5
    assert args.save_sensitive is True


def test_parser_rejects_negative_api_retries() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(["--api-retries", "-1"])
