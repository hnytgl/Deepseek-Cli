from __future__ import annotations

from pathlib import Path

from deepseek_cli.patch_review import apply_hunk_decisions, build_hunks


def test_apply_hunk_decisions_accepts_some_changes() -> None:
    old = "a\nkeep\nb\n"
    new = "A\nkeep\nB\n"
    hunks = build_hunks(Path("demo.txt"), old, new)

    result = apply_hunk_decisions(old, new, hunks, [True, False])

    assert result == "A\nkeep\nb\n"


def test_apply_hunk_decisions_can_edit_hunk_lines() -> None:
    old = "a\nkeep\nb\n"
    new = "A\nkeep\nB\n"
    hunks = build_hunks(Path("demo.txt"), old, new)

    result = apply_hunk_decisions(old, new, hunks, ["custom\n", False])

    assert result == "custom\nkeep\nb\n"


def test_build_hunks_reports_changed_regions() -> None:
    hunks = build_hunks(Path("demo.txt"), "a\nb\n", "a\nB\n")

    assert len(hunks) == 1
    assert "+B" in hunks[0].diff
