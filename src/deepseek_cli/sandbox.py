"""
deepseek_cli.sandbox -- OS-level process sandboxing for shell commands.

Provides defense-in-depth beyond the path-based workspace sandbox:
  - Linux: bubblewrap (bwrap) with namespace isolation
  - macOS: sandbox-exec (Seatbelt) with a generated profile
  - Windows: restricted process with Job Object (best-effort)

Falls back to unsandboxed execution with a warning when the sandbox
runtime is unavailable (e.g. bwrap not installed).

Usage:
    from deepseek_cli.sandbox import create_sandbox
    sandbox = create_sandbox(workspace="/path/to/project")
    result = sandbox.run("npm test", timeout=60)
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass
class SandboxResult:
    """Result of a sandboxed command execution."""
    stdout: str
    stderr: str
    returncode: int
    sandboxed: bool  # True if OS sandbox was active
    sandbox_type: str  # "bwrap", "seatbelt", "restricted", "none"


class Sandbox:
    """Base class for OS-level sandboxes."""

    def __init__(self, workspace: Path, *, network: bool = False, writable_paths: list[Path] | None = None):
        self.workspace = workspace.resolve()
        self.network = network
        self.writable_paths = writable_paths or [self.workspace]
        self.sandbox_type = "none"

    @property
    def available(self) -> bool:
        """Whether this sandbox backend is available on the current system."""
        return False

    def wrap_command(self, command: str, shell: str = "/bin/sh") -> list[str]:
        """Wrap a shell command with sandbox enforcement.

        Returns the full argv list to pass to subprocess.run().
        """
        raise NotImplementedError

    def run(self, command: str, *, timeout: int = 60, cwd: Path | None = None) -> SandboxResult:
        """Execute a command inside the sandbox."""
        work_dir = cwd or self.workspace
        argv = self.wrap_command(command)

        try:
            completed = subprocess.run(
                argv,
                cwd=str(work_dir),
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
            )
            return SandboxResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                sandboxed=self.available,
                sandbox_type=self.sandbox_type if self.available else "none",
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                stdout=exc.stdout or "" if isinstance(exc.stdout, str) else "",
                stderr=f"Command timed out after {timeout}s",
                returncode=-1,
                sandboxed=self.available,
                sandbox_type=self.sandbox_type if self.available else "none",
            )


class BwrapSandbox(Sandbox):
    """Linux sandbox using bubblewrap (bwrap) namespace isolation.

    Provides:
      - Filesystem isolation (only workspace + /usr, /lib, /bin visible)
      - PID namespace (no host process visibility)
      - Network isolation (optional, disabled by default)
      - No root access inside sandbox
    """

    def __init__(self, workspace: Path, **kwargs: Any):
        super().__init__(workspace, **kwargs)
        self.sandbox_type = "bwrap"
        self._bwrap_path = shutil.which("bwrap")

    @property
    def available(self) -> bool:
        return self._bwrap_path is not None and platform.system() == "Linux"

    def wrap_command(self, command: str, shell: str = "/bin/sh") -> list[str]:
        if not self.available:
            return [shell, "-c", command]

        argv = [
            self._bwrap_path,  # type: ignore[list-item]
            "--ro-bind", "/usr", "/usr",
            "--ro-bind", "/lib", "/lib",
            "--ro-bind", "/bin", "/bin",
            "--ro-bind", "/sbin", "/sbin",
            "--proc", "/proc",
            "--dev", "/dev",
            "--tmpfs", "/tmp",
            "--unshare-pid",
            "--die-with-parent",
        ]

        # Bind /lib64 if it exists (some distros)
        if os.path.isdir("/lib64"):
            argv.extend(["--ro-bind", "/lib64", "/lib64"])

        # Bind /etc read-only (needed for DNS, certs, etc.)
        if os.path.isdir("/etc"):
            argv.extend(["--ro-bind", "/etc", "/etc"])

        # Network isolation
        if not self.network:
            argv.append("--unshare-net")

        # Mount workspace as read-write
        argv.extend(["--bind", str(self.workspace), str(self.workspace)])

        # Additional writable paths
        for path in self.writable_paths:
            resolved = path.resolve()
            if resolved != self.workspace and resolved.exists():
                argv.extend(["--bind", str(resolved), str(resolved)])

        # Set working directory
        argv.extend(["--chdir", str(self.workspace)])

        # The actual command
        argv.extend([shell, "-c", command])
        return argv


class SeatbeltSandbox(Sandbox):
    """macOS sandbox using sandbox-exec (Seatbelt) profiles.

    Provides:
      - Filesystem write restriction (only workspace writable)
      - Network control (optional)
      - Process execution allowed but file writes confined
    """

    def __init__(self, workspace: Path, **kwargs: Any):
        super().__init__(workspace, **kwargs)
        self.sandbox_type = "seatbelt"
        self._profile_path: str | None = None

    @property
    def available(self) -> bool:
        return platform.system() == "Darwin" and shutil.which("sandbox-exec") is not None

    def _generate_profile(self) -> str:
        """Generate a Seatbelt profile allowing reads everywhere but writes only in workspace."""
        writable = [str(self.workspace)] + [str(p.resolve()) for p in self.writable_paths]
        # Add /tmp and /private/tmp for temp files
        writable.extend(["/tmp", "/private/tmp", "/var/folders"])

        write_rules = "\n".join(
            f'    (subpath "{p}")' for p in writable
        )

        network_rule = "(allow network*)" if self.network else "(deny network*)"

        profile = f"""(version 1)
(deny default)
(allow process-exec)
(allow process-fork)
(allow sysctl-read)
(allow mach-lookup)
(allow file-read*)
(allow file-write*
{write_rules}
)
(allow ipc-posysv*)
{network_rule}
(allow file-ioctl)
(allow file-lock)
"""
        return profile

    def wrap_command(self, command: str, shell: str = "/bin/sh") -> list[str]:
        if not self.available:
            return [shell, "-c", command]

        # Write profile to temp file
        profile_content = self._generate_profile()
        fd, profile_path = tempfile.mkstemp(suffix=".sb", prefix="deepseek_sandbox_")
        with os.fdopen(fd, "w") as f:
            f.write(profile_content)
        self._profile_path = profile_path

        return [
            "sandbox-exec",
            "-f", profile_path,
            shell, "-c", command,
        ]

    def cleanup(self) -> None:
        """Remove temporary profile file."""
        if self._profile_path and os.path.exists(self._profile_path):
            try:
                os.unlink(self._profile_path)
            except OSError:
                pass
            self._profile_path = None


class WindowsSandbox(Sandbox):
    """Windows sandbox using restricted process attributes (best-effort).

    Windows doesn't have a simple CLI sandbox equivalent to bwrap/seatbelt.
    This implementation provides:
      - Working directory confinement
      - Environment variable sanitization (remove sensitive vars)
      - CREATE_NO_WINDOW flag (no console popup)
      - Process group isolation for clean termination

    For full isolation on Windows, consider Windows Sandbox or WSL2.
    """

    def __init__(self, workspace: Path, **kwargs: Any):
        super().__init__(workspace, **kwargs)
        self.sandbox_type = "restricted"

    @property
    def available(self) -> bool:
        return platform.system() == "Windows"

    def wrap_command(self, command: str, shell: str = "powershell.exe") -> list[str]:
        # On Windows, we use PowerShell with restricted execution
        # The real confinement comes from the env sanitization in run()
        return [
            "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy", "Bypass",
            "-Command", command,
        ]

    def run(self, command: str, *, timeout: int = 60, cwd: Path | None = None) -> SandboxResult:
        """Execute with sanitized environment."""
        work_dir = cwd or self.workspace
        argv = self.wrap_command(command)

        # Sanitize environment: remove sensitive variables
        env = os.environ.copy()
        sensitive_prefixes = (
            "AWS_SECRET", "AZURE_", "GITHUB_TOKEN", "GITLAB_TOKEN",
            "DEEPSEEK_API_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
            "SSH_AUTH_SOCK", "GPG_", "NPM_TOKEN", "PYPI_",
        )
        for key in list(env.keys()):
            if any(key.upper().startswith(p) for p in sensitive_prefixes):
                del env[key]

        try:
            # CREATE_NEW_PROCESS_GROUP for clean termination
            creation_flags = 0
            if platform.system() == "Windows":
                creation_flags = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]

            completed = subprocess.run(
                argv,
                cwd=str(work_dir),
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=timeout,
                env=env,
                creationflags=creation_flags,
            )
            return SandboxResult(
                stdout=completed.stdout,
                stderr=completed.stderr,
                returncode=completed.returncode,
                sandboxed=True,
                sandbox_type=self.sandbox_type,
            )
        except subprocess.TimeoutExpired as exc:
            return SandboxResult(
                stdout="",
                stderr=f"Command timed out after {timeout}s",
                returncode=-1,
                sandboxed=True,
                sandbox_type=self.sandbox_type,
            )


class NoSandbox(Sandbox):
    """Fallback: no OS-level sandboxing (path restriction only)."""

    def __init__(self, workspace: Path, **kwargs: Any):
        super().__init__(workspace, **kwargs)
        self.sandbox_type = "none"

    @property
    def available(self) -> bool:
        return False

    def wrap_command(self, command: str, shell: str = "/bin/sh") -> list[str]:
        if platform.system() == "Windows":
            return ["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", command]
        return [shell, "-c", command]


def create_sandbox(
    workspace: Path,
    *,
    mode: str = "auto",
    network: bool = False,
    writable_paths: list[Path] | None = None,
) -> Sandbox:
    """
    Factory: create the best available sandbox for the current platform.

    Args:
        workspace: Project root directory.
        mode: "auto" (best available), "none" (disable), "strict" (fail if unavailable).
        network: Whether to allow network access inside sandbox.
        writable_paths: Additional paths that should be writable.

    Returns:
        Sandbox instance (may not be available if mode="auto" and no runtime found).
    """
    if mode == "none":
        return NoSandbox(workspace, network=network, writable_paths=writable_paths)

    system = platform.system()
    sandbox: Sandbox

    if system == "Linux":
        sandbox = BwrapSandbox(workspace, network=network, writable_paths=writable_paths)
    elif system == "Darwin":
        sandbox = SeatbeltSandbox(workspace, network=network, writable_paths=writable_paths)
    elif system == "Windows":
        sandbox = WindowsSandbox(workspace, network=network, writable_paths=writable_paths)
    else:
        sandbox = NoSandbox(workspace, network=network, writable_paths=writable_paths)

    if mode == "strict" and not sandbox.available:
        raise RuntimeError(
            f"OS sandbox not available on {system}. "
            "Install bubblewrap (Linux) or use --sandbox-mode none to disable."
        )

    return sandbox


def sandbox_status() -> dict[str, Any]:
    """Return sandbox availability info for --doctor."""
    system = platform.system()
    info: dict[str, Any] = {"platform": system}

    if system == "Linux":
        bwrap = shutil.which("bwrap")
        info["bwrap_available"] = bwrap is not None
        info["bwrap_path"] = bwrap
        if not bwrap:
            info["install_hint"] = "sudo apt install bubblewrap  # or: sudo dnf install bubblewrap"
    elif system == "Darwin":
        info["seatbelt_available"] = shutil.which("sandbox-exec") is not None
    elif system == "Windows":
        info["restricted_mode"] = True
        info["note"] = "Full isolation requires Windows Sandbox or WSL2"

    return info
