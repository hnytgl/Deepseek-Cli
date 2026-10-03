from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex


class PolicyViolation(RuntimeError):
    """Raised when a tool violates the configured policy."""


# Backward-compatible alias (deprecated, use PolicyViolation)
PermissionError = PolicyViolation


def normalize_approval(value: str) -> str:
    aliases = {"suggest": "read-only", "full-auto": "auto"}
    normalized = aliases.get(value, value)
    if normalized not in {"read-only", "ask", "auto-edit", "auto"}:
        raise PolicyViolation(f"Invalid approval mode: {value}")
    return normalized


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
        return normalize_approval(self.approval) == "auto"

    @property
    def read_only(self) -> bool:
        return normalize_approval(self.approval) == "read-only"

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
        for key in ("shell", "install_tools"):
            if key in data and not isinstance(data[key], bool):
                raise PolicyViolation(f"{key} must be a boolean.")
        for key in ("allow_commands", "deny_commands"):
            if key in data and (not isinstance(data[key], list) or not all(isinstance(item, str) for item in data[key])):
                raise PolicyViolation(f"{key} must be a list of command names.")
        sandbox = str(data.get("sandbox") or "workspace")
        if sandbox not in {"workspace", "unrestricted"}:
            raise PolicyViolation(f"Invalid sandbox: {sandbox}")
        return cls(
            approval=normalize_approval(str(data.get("approval") or "ask")),
            sandbox=sandbox,
            shell=bool(data.get("shell", True)),
            allow_commands=tuple(str(item).lower() for item in data.get("allow_commands", []) or []),
            deny_commands=tuple(str(item).lower() for item in data.get("deny_commands", []) or []),
            install_tools=bool(data.get("install_tools", False)),
        )


def restrict_policy(policy: PermissionConfig, data: dict[str, object]) -> PermissionConfig:
    """Intersect an untrusted project's restrictions with authorized settings."""
    approval = normalize_approval(policy.approval)
    ranks = {"read-only": 0, "ask": 1, "auto-edit": 2, "auto": 3}
    if "approval" in data:
        requested = normalize_approval(str(data["approval"]))
        approval = min((approval, requested), key=ranks.__getitem__)
    sandbox = policy.sandbox
    if "sandbox" in data:
        requested_sandbox = str(data["sandbox"])
        if requested_sandbox not in {"workspace", "unrestricted"}:
            raise PolicyViolation(f"Invalid sandbox: {requested_sandbox}")
        if requested_sandbox == "workspace":
            sandbox = "workspace"
    shell = policy.shell and bool(data.get("shell", True))
    allow = tuple(_normalized_command(item) for item in policy.allow_commands)
    deny = tuple(_normalized_command(item) for item in policy.deny_commands)
    for key in ("allow_commands", "deny_commands"):
        if key in data and not isinstance(data[key], (list, tuple)):
            raise PolicyViolation(f"{key} must be a list of command names.")
    requested_allow = tuple(_normalized_command(str(item)) for item in data.get("allow_commands", []) or [])
    if requested_allow:
        if allow:
            allow = tuple(item for item in allow if item in requested_allow)
            # Empty intersection must not turn into the unrestricted empty list.
            if not allow:
                shell = False
        else:
            allow = requested_allow
    deny = tuple(dict.fromkeys((*deny, *(_normalized_command(str(item)) for item in data.get("deny_commands", []) or []))))
    return PermissionConfig(
        approval=approval, sandbox=sandbox, shell=shell,
        allow_commands=allow, deny_commands=deny,
        install_tools=policy.install_tools and bool(data.get("install_tools", True)),
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
            inner = _interpreter_command(segment, name)
            if inner:
                names.extend(command_names(inner))
    return tuple(names)


def _interpreter_command(segment: str, name: str) -> str | None:
    normalized = _normalized_command(name)
    try:
        parts = shlex.split(segment.lstrip("() "), posix=False)
    except ValueError:
        return None
    options = {
        "powershell": {"-command", "-c"},
        "pwsh": {"-command", "-c"},
        "cmd": {"/c", "/k"},
        "bash": {"-c"},
        "sh": {"-c"},
        "zsh": {"-c"},
    }
    if normalized not in options:
        return None
    for index, part in enumerate(parts[1:], start=1):
        if part.lower() in options[normalized] and index + 1 < len(parts):
            return " ".join(parts[index + 1 :]).strip("\"'")
    return None


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
