from __future__ import annotations

import argparse
import hashlib
from pathlib import Path


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def replace(path: Path, replacements: dict[str, str]) -> None:
    text = path.read_text(encoding="utf-8")
    for old, new in replacements.items():
        text = text.replace(old, new)
    path.write_text(text, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update package manager manifests with release SHA256 values.")
    parser.add_argument("--version", required=True)
    parser.add_argument("--homebrew-tar", type=Path)
    parser.add_argument("--scoop-zip", type=Path)
    parser.add_argument("--winget-windows-zip", type=Path)
    parser.add_argument("--check", action="store_true", help="Fail if placeholders remain.")
    args = parser.parse_args()

    root = Path(__file__).resolve().parents[1]
    replacements = {
        "v0.8.0": f"v{args.version}",
        "0.8.0": args.version,
    }
    if args.homebrew_tar:
        replacements["REPLACE_WITH_RELEASE_TARBALL_SHA256"] = sha256(args.homebrew_tar)
    if args.scoop_zip:
        replacements["REPLACE_WITH_RELEASE_ZIP_SHA256"] = sha256(args.scoop_zip)
    if args.winget_windows_zip:
        replacements["REPLACE_WITH_WINDOWS_ZIP_SHA256"] = sha256(args.winget_windows_zip)

    targets = [
        root / "packaging" / "homebrew" / "deepseek-codex-cli.rb",
        root / "packaging" / "scoop" / "deepseek-codex-cli.json",
        root / "packaging" / "winget" / "Hnytgl.DeepseekCodexCli.installer.yaml",
        root / "packaging" / "winget" / "Hnytgl.DeepseekCodexCli.locale.en-US.yaml",
        root / "packaging" / "winget" / "Hnytgl.DeepseekCodexCli.yaml",
    ]
    for target in targets:
        replace(target, replacements)

    if args.check:
        remaining = []
        for target in targets:
            text = target.read_text(encoding="utf-8")
            if "REPLACE_WITH_" in text:
                remaining.append(str(target))
        if remaining:
            raise SystemExit("Placeholders remain:\n" + "\n".join(remaining))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
