from __future__ import annotations

import pytest

from deepseek_cli.tool_installer import build_command, manager_candidates, resolve_install_plan


def test_manager_candidates_by_os() -> None:
    assert manager_candidates("Windows")[:3] == ["winget", "scoop", "choco"]
    assert manager_candidates("Darwin")[0] == "brew"
    assert manager_candidates("Linux")[:4] == ["apt", "dnf", "pacman", "zypper"]


def test_build_winget_command() -> None:
    assert build_command("winget", "Git.Git") == [
        "winget",
        "install",
        "--id",
        "Git.Git",
        "--accept-package-agreements",
        "--accept-source-agreements",
    ]


def test_explicit_manager_maps_known_tool_package() -> None:
    plan = resolve_install_plan(tool_name="ripgrep", manager="winget")

    assert plan.manager == "winget"
    assert plan.package == "BurntSushi.ripgrep.MSVC"
    assert "BurntSushi.ripgrep.MSVC" in plan.command


def test_explicit_package_overrides_mapping() -> None:
    plan = resolve_install_plan(tool_name="ripgrep", manager="brew", package="custom-rg")

    assert plan.package == "custom-rg"
    assert plan.command == ["brew", "install", "custom-rg"]


def test_unknown_manager_fails() -> None:
    with pytest.raises(Exception):
        resolve_install_plan(tool_name="jq", manager="unknown")
