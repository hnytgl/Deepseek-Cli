from __future__ import annotations

import shutil
import subprocess
import sys
from dataclasses import dataclass

from . import __version__


@dataclass(frozen=True)
class DoctorReport:
    ok: bool
    output: str


def run_doctor() -> DoctorReport:
    rows: list[str] = [f"deepseek-codex-cli {__version__}", f"python {sys.version.split()[0]}"]
    checks = {
        "git": shutil.which("git"),
        "gh": shutil.which("gh"),
    }
    ok = True
    for name, path in checks.items():
        if path:
            rows.append(f"[ok] {name}: {path}")
        else:
            ok = False
            rows.append(f"[missing] {name}")

    if checks["gh"]:
        completed = subprocess.run(
            ["gh", "auth", "status"],
            text=True,
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=30,
        )
        rows.append("[ok] gh auth" if completed.returncode == 0 else "[warn] gh auth not ready")

    return DoctorReport(ok=ok, output="\n".join(rows))


def self_update(source: str) -> int:
    command = [sys.executable, "-m", "pip", "install", "--upgrade", source]
    completed = subprocess.run(command, text=True, errors="replace")
    return completed.returncode
