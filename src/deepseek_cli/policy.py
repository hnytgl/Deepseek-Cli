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
        names = command_names(command)
        if not names:
            raise PermissionError("Empty shell command is not allowed.")
        denied = next((name for name in names if _matches_command(name, self.deny_commands)), None)
        if denied:
            raise PermissionError(f"Command is blocked by policy: {denied}")
        disallowed = next((name for name in names if not _matches_command(name, self.allow_commands)), None)
        if self.allow_commands and disallowed:
            allowed = ", ".join(self.allow_commands)
            raise PermissionError(f"Command is not in allowlist: {disallowed}. Allowed: {allowed}")

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
    return _portable_basename(executable).lower()


def command_names(command: str) -> tuple[str, ...]:
    names: list[str] = []
    for segment in _split_shell_commands(command):
        name = command_name(segment.lstrip("() "))
        if name:
            names.append(name)
    return tuple(names)


def _split_shell_commands(command: str) -> list[str]:
    segments: list[str] = []
    current: list[str] = []
    quote: str | None = None
    index = 0
    while index < len(command):
        char = command[index]
        if quote:
            current.append(char)
            if char == quote:
                quote = None
            elif char == "\\" and index + 1 < len(command):
                index += 1
                current.append(command[index])
        elif char in {"'", '"'}:
            quote = char
            current.append(char)
        elif char in {";", "|", "&", "\n", "\r"}:
            segment = "".join(current).strip()
            if segment:
                segments.append(segment)
            current = []
            while index + 1 < len(command) and command[index + 1] in {";", "|", "&", "\n", "\r"}:
                index += 1
        else:
            current.append(char)
        index += 1
    segment = "".join(current).strip()
    if segment:
        segments.append(segment)
    return segments


def _matches_command(name: str, configured: tuple[str, ...]) -> bool:
    if not configured:
        return False
    normalized = _normalized_command(name)
    return any(normalized == _normalized_command(item) for item in configured)


def _normalized_command(name: str) -> str:
    lowered = _portable_basename(name.strip("\"'")).lower()
    for suffix in (".exe", ".cmd", ".bat", ".com"):
        if lowered.endswith(suffix):
            return lowered[: -len(suffix)]
    return lowered


def _portable_basename(value: str) -> str:
    return value.replace("\\", "/").rsplit("/", 1)[-1]


def project_policy_path(cwd: Path) -> Path:
    return cwd.resolve() / ".deepseek-cli" / "policy.json"


def load_project_policy(cwd: Path) -> PermissionConfig:
    path = project_policy_path(cwd)
    if not path.exists():
        return PermissionConfig()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PermissionError(f"Could not read policy file {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise PermissionError(f"Invalid policy file: {path}")
    return PermissionConfig.from_dict(data)


def save_project_policy(cwd: Path, policy: PermissionConfig) -> Path:
    path = project_policy_path(cwd)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return path
