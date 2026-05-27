from __future__ import annotations

from deepseek_cli.policy import command_name
from deepseek_cli.policy import PermissionConfig, load_project_policy, save_project_policy


def test_command_name_extracts_executable() -> None:
    assert command_name("python -m pytest") == "python"
    assert command_name('"C:\\Program Files\\Git\\bin\\git.exe" status') == "git.exe"


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
