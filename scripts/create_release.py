from __future__ import annotations

import argparse
import subprocess


def main() -> int:
    parser = argparse.ArgumentParser(description="Create a GitHub release with generated release notes.")
    parser.add_argument("version", help="Version such as 0.5.0 or v0.5.0.")
    parser.add_argument("--title", default=None)
    parser.add_argument("--draft", action="store_true")
    args = parser.parse_args()

    tag = args.version if args.version.startswith("v") else f"v{args.version}"
    command = ["gh", "release", "create", tag, "--generate-notes", "--title", args.title or tag]
    if args.draft:
        command.append("--draft")
    return subprocess.run(command).returncode


if __name__ == "__main__":
    raise SystemExit(main())
