from __future__ import annotations

import platform
import shutil
from dataclasses import dataclass


class ToolInstallError(RuntimeError):
    """Raised when no safe install plan can be produced."""


TOOL_PACKAGES: dict[str, dict[str, str]] = {
    "ripgrep": {
        "winget": "BurntSushi.ripgrep.MSVC",
        "scoop": "ripgrep",
        "choco": "ripgrep",
        "brew": "ripgrep",
        "apt": "ripgrep",
        "dnf": "ripgrep",
        "pacman": "ripgrep",
        "zypper": "ripgrep",
        "npm": "@vscode/ripgrep",
    },
    "rg": {
        "winget": "BurntSushi.ripgrep.MSVC",
        "scoop": "ripgrep",
        "choco": "ripgrep",
        "brew": "ripgrep",
        "apt": "ripgrep",
        "dnf": "ripgrep",
        "pacman": "ripgrep",
        "zypper": "ripgrep",
        "npm": "@vscode/ripgrep",
    },
    "fd": {
        "winget": "sharkdp.fd",
        "scoop": "fd",
        "choco": "fd",
        "brew": "fd",
        "apt": "fd-find",
        "dnf": "fd-find",
        "pacman": "fd",
        "zypper": "fd",
    },
    "jq": {
        "winget": "jqlang.jq",
        "scoop": "jq",
        "choco": "jq",
        "brew": "jq",
        "apt": "jq",
        "dnf": "jq",
        "pacman": "jq",
        "zypper": "jq",
    },
    "git": {
        "winget": "Git.Git",
        "scoop": "git",
        "choco": "git",
        "brew": "git",
        "apt": "git",
        "dnf": "git",
        "pacman": "git",
        "zypper": "git",
    },
    "gh": {
        "winget": "GitHub.cli",
        "scoop": "gh",
        "choco": "gh",
        "brew": "gh",
        "apt": "gh",
        "dnf": "gh",
        "pacman": "github-cli",
        "zypper": "gh",
    },
    "node": {
        "winget": "OpenJS.NodeJS.LTS",
        "scoop": "nodejs-lts",
        "choco": "nodejs-lts",
        "brew": "node",
        "apt": "nodejs",
        "dnf": "nodejs",
        "pacman": "nodejs",
        "zypper": "nodejs",
    },
}


MANAGER_COMMANDS: dict[str, list[str]] = {
    "pip": ["python", "-m", "pip", "install"],
    "npm": ["npm", "install", "-g"],
    "winget": ["winget", "install", "--id", "{package}", "--accept-package-agreements", "--accept-source-agreements"],
    "scoop": ["scoop", "install"],
    "choco": ["choco", "install", "-y"],
    "brew": ["brew", "install"],
    "apt": ["sudo", "apt-get", "install", "-y"],
    "dnf": ["sudo", "dnf", "install", "-y"],
    "pacman": ["sudo", "pacman", "-S", "--noconfirm"],
    "zypper": ["sudo", "zypper", "install", "-y"],
}


@dataclass(frozen=True)
class InstallPlan:
    manager: str
    package: str
    command: list[str]

    def display(self) -> str:
        return " ".join(self.command)


def manager_candidates(system: str | None = None) -> list[str]:
    resolved = (system or platform.system()).lower()
    if resolved == "windows":
        return ["winget", "scoop", "choco", "npm", "pip"]
    if resolved == "darwin":
        return ["brew", "npm", "pip"]
    if resolved == "linux":
        return ["apt", "dnf", "pacman", "zypper", "brew", "npm", "pip"]
    return ["npm", "pip"]


def available_managers(candidates: list[str] | None = None) -> list[str]:
    names = candidates or manager_candidates()
    return [name for name in names if manager_available(name)]


def manager_available(name: str) -> bool:
    if name == "apt":
        return shutil.which("apt-get") is not None
    if name == "pacman":
        return shutil.which("pacman") is not None
    return shutil.which(name) is not None


def resolve_package(tool_name: str, manager: str, explicit_package: str | None = None) -> str:
    if explicit_package:
        return explicit_package
    packages = TOOL_PACKAGES.get(tool_name.lower())
    if packages and manager in packages:
        return packages[manager]
    return tool_name


def build_command(manager: str, package: str) -> list[str]:
    if manager not in MANAGER_COMMANDS:
        raise ToolInstallError(f"Unsupported package manager: {manager}")
    template = MANAGER_COMMANDS[manager]
    if "{package}" in template:
        return [package if part == "{package}" else part for part in template]
    return [*template, package]


def resolve_install_plan(
    *,
    tool_name: str | None = None,
    manager: str | None = None,
    package: str | None = None,
    system: str | None = None,
) -> InstallPlan:
    if manager:
        chosen = manager.lower()
        resolved_package = resolve_package(tool_name or package or "", chosen, package)
        return InstallPlan(chosen, resolved_package, build_command(chosen, resolved_package))

    if not tool_name and not package:
        raise ToolInstallError("install_tool requires name or package.")

    logical_name = tool_name or package or ""
    for candidate in available_managers(manager_candidates(system)):
        try:
            resolved_package = resolve_package(logical_name, candidate, package)
            return InstallPlan(candidate, resolved_package, build_command(candidate, resolved_package))
        except ToolInstallError:
            continue

    candidates = ", ".join(manager_candidates(system))
    raise ToolInstallError(f"No supported package manager is available. Tried: {candidates}")
