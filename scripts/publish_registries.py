from __future__ import annotations

import argparse
import subprocess
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None) -> None:
    completed = subprocess.run(command, cwd=cwd)
    if completed.returncode != 0:
        raise SystemExit(completed.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish prepared manifests to real package registries.")
    parser.add_argument("--pypi", action="store_true", help="Upload dist/* to PyPI using twine.")
    parser.add_argument("--homebrew-tap", help="Path to a checked out Homebrew tap repository.")
    parser.add_argument("--scoop-bucket", help="Path to a checked out Scoop bucket repository.")
    parser.add_argument("--winget-pkgs", help="Path to a checked out winget-pkgs repository.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    commands: list[tuple[list[str], Path | None]] = []
    if args.pypi:
        commands.append((["python", "-m", "twine", "upload", "dist/*"], root))
    if args.homebrew_tap:
        target = Path(args.homebrew_tap) / "Formula" / "deepseek-codex-cli.rb"
        commands.append((["python", "-c", f"import shutil; shutil.copyfile(r'{root / 'packaging/homebrew/deepseek-codex-cli.rb'}', r'{target}')"], None))
    if args.scoop_bucket:
        target = Path(args.scoop_bucket) / "bucket" / "deepseek-codex-cli.json"
        commands.append((["python", "-c", f"import shutil; shutil.copyfile(r'{root / 'packaging/scoop/deepseek-codex-cli.json'}', r'{target}')"], None))
    if args.winget_pkgs:
        target_dir = Path(args.winget_pkgs) / "manifests" / "h" / "Hnytgl" / "DeepseekCodexCli"
        commands.append((["python", "-c", f"import shutil, pathlib; pathlib.Path(r'{target_dir}').mkdir(parents=True, exist_ok=True); shutil.copytree(r'{root / 'packaging/winget'}', r'{target_dir}', dirs_exist_ok=True)"], None))

    for command, cwd in commands:
        print("+", " ".join(command))
        if not args.dry_run:
            run(command, cwd=cwd)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
