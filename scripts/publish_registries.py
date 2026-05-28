from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path


def run(command: list[str], *, cwd: Path | None = None, capture: bool = False) -> str:
    completed = subprocess.run(command, cwd=cwd, text=True, stdout=subprocess.PIPE if capture else None, stderr=subprocess.PIPE if capture else None)
    if completed.returncode != 0:
        if capture:
            print(completed.stdout)
            print(completed.stderr)
        raise SystemExit(completed.returncode)
    return completed.stdout if capture else ""


def copy_manifest(source: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)


def copy_tree(source: Path, target: Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, target, dirs_exist_ok=True)


def open_registry_pr(repo: Path, branch: str, title: str, body: str, dry_run: bool) -> None:
    commands = [
        ["git", "checkout", "-B", branch],
        ["git", "add", "."],
        ["git", "commit", "-m", title],
        ["git", "push", "-u", "origin", branch],
        ["gh", "pr", "create", "--title", title, "--body", body],
    ]
    for command in commands:
        print("+", " ".join(command), f"(cwd={repo})")
        if not dry_run:
            try:
                run(command, cwd=repo)
            except SystemExit as exc:
                if command[:3] == ["git", "commit", "-m"]:
                    status = run(["git", "status", "--porcelain"], cwd=repo, capture=True)
                    if not status.strip():
                        print("No registry changes to commit.")
                        return
                raise exc


def pypi_has_version(package: str, version: str) -> bool:
    url = f"https://pypi.org/pypi/{package}/{version}/json"
    try:
        with urllib.request.urlopen(url, timeout=20) as response:
            return response.status == 200
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def gh_search(query: str) -> int:
    output = run(["gh", "search", "code", query, "--json", "path", "--limit", "1"], capture=True)
    return len(json.loads(output or "[]"))


def check_status(version: str) -> None:
    checks = {
        "PyPI": pypi_has_version("deepseek-codex-cli", version),
        "Homebrew": gh_search(f'"v{version}.tar.gz" "deepseek-codex-cli.rb"') > 0,
        "Scoop": gh_search(f'"deepseek-codex-cli" "{version}" filename:deepseek-codex-cli.json') > 0,
        "winget": gh_search(f'"Hnytgl.DeepseekCodexCli" "{version}"') > 0,
    }
    for name, ok in checks.items():
        print(f"{name}: {'published' if ok else 'not found'}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Publish prepared manifests to real package registries.")
    parser.add_argument("--pypi", action="store_true", help="Upload dist/* to PyPI using twine.")
    parser.add_argument("--homebrew-tap", help="Path to a checked out Homebrew tap repository.")
    parser.add_argument("--scoop-bucket", help="Path to a checked out Scoop bucket repository.")
    parser.add_argument("--winget-pkgs", help="Path to a checked out winget-pkgs repository.")
    parser.add_argument("--version", default="0.8.0", help="Version used in registry PR branch names and status checks.")
    parser.add_argument("--open-pr", action="store_true", help="Commit, push, and open PRs in the registry repositories.")
    parser.add_argument("--check-status", action="store_true", help="Check whether the version appears in PyPI/Homebrew/Scoop/winget.")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    commands: list[tuple[list[str], Path | None]] = []
    pr_targets: list[tuple[Path, str, str, str]] = []
    if args.check_status:
        check_status(args.version)
        return 0
    if args.pypi:
        commands.append((["python", "-m", "twine", "upload", "dist/*"], root))
    if args.homebrew_tap:
        target = Path(args.homebrew_tap) / "Formula" / "deepseek-codex-cli.rb"
        print("+ copy", root / "packaging/homebrew/deepseek-codex-cli.rb", target)
        if not args.dry_run:
            copy_manifest(root / "packaging/homebrew/deepseek-codex-cli.rb", target)
        pr_targets.append((Path(args.homebrew_tap), f"deepseek-codex-cli-{args.version}", f"deepseek-codex-cli {args.version}", "Update DeepSeek Codex CLI formula."))
    if args.scoop_bucket:
        target = Path(args.scoop_bucket) / "bucket" / "deepseek-codex-cli.json"
        print("+ copy", root / "packaging/scoop/deepseek-codex-cli.json", target)
        if not args.dry_run:
            copy_manifest(root / "packaging/scoop/deepseek-codex-cli.json", target)
        pr_targets.append((Path(args.scoop_bucket), f"deepseek-codex-cli-{args.version}", f"deepseek-codex-cli {args.version}", "Update DeepSeek Codex CLI Scoop manifest."))
    if args.winget_pkgs:
        target_dir = Path(args.winget_pkgs) / "manifests" / "h" / "Hnytgl" / "DeepseekCodexCli"
        print("+ copytree", root / "packaging/winget", target_dir)
        if not args.dry_run:
            copy_tree(root / "packaging/winget", target_dir)
        pr_targets.append((Path(args.winget_pkgs), f"hnytgl-deepseek-codex-cli-{args.version}", f"Hnytgl.DeepseekCodexCli {args.version}", "Update DeepSeek Codex CLI winget manifests."))

    for command, cwd in commands:
        print("+", " ".join(command))
        if not args.dry_run:
            run(command, cwd=cwd)
    if args.open_pr:
        for repo, branch, title, body in pr_targets:
            open_registry_pr(repo, branch, title, body, args.dry_run)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
