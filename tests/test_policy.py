from __future__ import annotations

import pytest

from deepseek_cli.policy import PermissionError, command_name, command_names
from deepseek_cli.policy import PermissionConfig, load_project_policy, save_project_policy


def test_command_name_extracts_executable() -> None:
    assert command_name("python -m pytest") == "python"
    assert command_name('"C:\\Program Files\\Git\\bin\\git.exe" status') == "git.exe"


def test_command_names_extracts_compound_commands() -> None:
    assert command_names('python -c "print(1; 2)" && git status | findstr main') == (
        "python",
        "git",
        "findstr",
    )


def test_command_policy_checks_every_compound_command() -> None:
    policy = PermissionConfig(allow_commands=("python", "git"))

    policy.check_command("python --version && git status")
    with pytest.raises(PermissionError, match="not in allowlist: rm"):
        policy.check_command("python --version && rm -rf build")


def test_command_policy_matches_windows_executable_suffixes() -> None:
    PermissionConfig(allow_commands=("python",)).check_command("python.exe --version")
    with pytest.raises(PermissionError, match="blocked by policy"):
        PermissionConfig(deny_commands=("git",)).check_command("git.exe status")


def test_project_policy_round_trip(tmp_path) -> None:
    policy = PermissionConfig(
        approval="auto",
        sandbox="unrestricted",
        shell=False,
        allow_commands=("python",),
        deny_commands=("rm",),
        install_tools=True,
    )

    save_project_policy(tmp_path, policy)

    assert load_project_policy(tmp_path) == policy


def test_invalid_project_policy_has_clear_error(tmp_path) -> None:
    path = tmp_path / ".deepseek-cli" / "policy.json"
    path.parent.mkdir()
    path.write_text("{", encoding="utf-8")

    with pytest.raises(PermissionError, match="Could not read policy file"):
        load_project_policy(tmp_path)
