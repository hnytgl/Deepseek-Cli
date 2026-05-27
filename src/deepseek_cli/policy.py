from __future__ import annotations

from dataclasses import dataclass
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


def command_name(command: str) -> str:
    try:
        parts = shlex.split(command, posix=False)
    except ValueError:
        parts = command.strip().split()
    if not parts:
        return ""
    executable = parts[0].strip("\"'")
    return Path(executable).name.lower()
