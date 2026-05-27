from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex


class PermissionError(RuntimeError):
    """Raised when a tool violates the configured policy."""


@dataclass(frozen=True)
class PermissionConfig:
    approval: str = "ask"
    sandbox: str = "workspace"
    shell: bool = True
    allow_commands: tuple[str, ...] = ()
    deny_commands: tuple[str, ...] = ()
    install_tools: bool = False

    @property
    def auto_approve(self) -> bool:
        return self.approval == "auto"

    @property
    def read_only(self) -> bool:
        return self.approval == "read-only"

    def check_path(self, cwd: Path, path: Path) -> None:
        if self.sandbox == "unrestricted":
            return
        try:
            path.relative_to(cwd.resolve())
        except ValueError as exc:
            raise PermissionError(f"Path is outside workspace sandbox: {path}") from exc

    def check_write(self) -> None:
        if self.read_only:
            raise PermissionError("Write tools are disabled in read-only approval mode.")

    def check_shell(self) -> None:
        if self.read_only:
            raise PermissionError("Shell tools are disabled in read-only approval mode.")
        if not self.shell:
            raise PermissionError("Shell tools are disabled by configuration.")

    def check_command(self, command: str) -> None:
        self.check_shell()
        name = command_name(command)
        if not name:
            raise PermissionError("Empty shell command is not allowed.")
        if self.deny_commands and name in self.deny_commands:
            raise PermissionError(f"Command is blocked by policy: {name}")
        if self.allow_commands and name not in self.allow_commands:
            allowed = ", ".join(self.allow_commands)
            raise PermissionError(f"Command is not in allowlist: {name}. Allowed: {allowed}")

    def check_install_tools(self) -> None:
        self.check_shell()
        if not self.install_tools:
            raise PermissionError("Tool installation is disabled. Re-run with --allow-install-tools.")

    def to_dict(self) -> dict[str, object]:
        return {
            "approval": self.approval,
            "sandbox": self.sandbox,
            "shell": self.shell,
            "allow_commands": list(self.allow_commands),
            "deny_commands": list(self.deny_commands),
            "install_tools": self.install_tools,
        }

    @classmethod
    def from_dict(cls, data: dict[str, object]) -> "PermissionConfig":
        return cls(
            approval=str(data.get("approval") or "ask"),
            sandbox=str(data.get("sandbox") or "workspace"),
            shell=bool(data.get("shell", True)),
            allow_commands=tuple(str(item).lower() for item in data.get("allow_commands", []) or []),
            deny_commands=tuple(str(item).lower() for item in data.get("deny_commands", []) or []),
            install_tools=bool(data.get("install_tools", False)),
        )


def command_name(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.strip().split()
    if not parts:
        return ""
    executable = parts[0].strip("\"'")
    return Path(executable).name.lower()


def project_policy_path(cwd: Path) -> Path:
    return cwd.resolve() / ".deepseek-cli" / "policy.json"


def load_project_policy(cwd: Path) -> PermissionConfig:
    path = project_policy_path(cwd)
    if not path.exists():
        return PermissionConfig()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise PermissionError(f"Invalid policy file: {path}")
    return PermissionConfig.from_dict(data)


def save_project_policy(cwd: Path, policy: PermissionConfig) -> Path:
    path = project_policy_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
