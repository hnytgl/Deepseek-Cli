from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


class PermissionError(RuntimeError):
    """Raised when a tool violates the configured policy."""


@dataclass(frozen=True)
class PermissionConfig:
    approval: str = "ask"
    sandbox: str = "workspace"
    shell: bool = True

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
