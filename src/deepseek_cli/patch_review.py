from __future__ import annotations

import difflib
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class PatchHunk:
    path: Path
    old_start: int
    old_end: int
    new_start: int
    new_end: int
    diff: str


def build_hunks(path: Path, old: str, new: str) -> list[PatchHunk]:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    matcher = difflib.SequenceMatcher(a=old_lines, b=new_lines)
    hunks: list[PatchHunk] = []
    for tag, old_start, old_end, new_start, new_end in matcher.get_opcodes():
        if tag == "equal":
            continue
        old_chunk = old_lines[old_start:old_end]
        new_chunk = new_lines[new_start:new_end]
        diff = "".join(
            difflib.unified_diff(
                old_chunk,
                new_chunk,
                fromfile=f"a/{path.name}",
                tofile=f"b/{path.name}",
                lineterm="",
            )
        )
        hunks.append(
            PatchHunk(
                path=path,
                old_start=old_start,
                old_end=old_end,
                new_start=new_start,
                new_end=new_end,
                diff=diff,
            )
        )
    return hunks


def apply_hunk_decisions(old: str, new: str, hunks: list[PatchHunk], accepted: list[bool]) -> str:
    old_lines = old.splitlines(keepends=True)
    new_lines = new.splitlines(keepends=True)
    result: list[str] = []
    old_cursor = 0
    for hunk, accept in zip(hunks, accepted):
        result.extend(old_lines[old_cursor : hunk.old_start])
        if accept:
            result.extend(new_lines[hunk.new_start : hunk.new_end])
        else:
            result.extend(old_lines[hunk.old_start : hunk.old_end])
        old_cursor = hunk.old_end
    result.extend(old_lines[old_cursor:])
    return "".join(result)
