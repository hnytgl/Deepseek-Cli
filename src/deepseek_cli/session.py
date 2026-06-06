from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class SessionError(RuntimeError):
    """Raised when a saved session cannot be read."""


@dataclass(frozen=True)
class SessionRecord:
    name: str
    cwd: str
    model: str
    updated_at: int
    messages: list[dict[str, Any]]
    path: Path

    @property
    def preview(self) -> str:
        for message in reversed(self.messages):
            if message.get("role") == "user":
                content = str(message.get("content") or "").strip().replace("\n", " ")
                if "\n\n" in str(message.get("content") or ""):
                    content = str(message["content"]).split("\n\n", 1)[-1].strip().replace("\n", " ")
                return content[:100]
        return "(no user prompt)"


def default_session_dir() -> Path:
    return Path.home() / ".deepseek-cli" / "sessions"


@dataclass(frozen=True)
class SessionStore:
    root: Path

    @classmethod
    def default(cls) -> "SessionStore":
        return cls(default_session_dir())

    def path_for(self, name: str) -> Path:
        safe = "".join(ch if ch.isalnum() or ch in {"-", "_", "."} else "-" for ch in name).strip("-")
        if not safe:
            safe = "default"
        return self.root / f"{safe}.json"

    def latest_path(self) -> Path | None:
        if not self.root.exists():
            return None
        files = sorted(self.root.glob("*.json"), key=lambda path: path.stat().st_mtime, reverse=True)
        return files[0] if files else None

    def read(self, name: str | None = None, *, latest: bool = False) -> SessionRecord | None:
        path = self.latest_path() if latest else self.path_for(name or "default")
        if not path or not path.exists():
            return None
        data = self._read_data(path)
        messages = data.get("messages", [])
        if not isinstance(messages, list) or not all(isinstance(message, dict) for message in messages):
            raise SessionError(f"Invalid messages in session file: {path}")
        return SessionRecord(
            name=str(data.get("name") or path.stem),
            cwd=str(data.get("cwd") or ""),
            model=str(data.get("model") or ""),
            updated_at=int(data.get("updated_at") or int(path.stat().st_mtime)),
            messages=messages,
            path=path,
        )

    def load(self, name: str | None = None, *, latest: bool = False) -> list[dict[str, Any]]:
        record = self.read(name, latest=latest)
        return record.messages if record else []

    def search(self, query: str = "") -> list[SessionRecord]:
        if not self.root.exists():
            return []
        needle = query.casefold().strip()
        records: list[SessionRecord] = []
        for path in self.root.glob("*.json"):
            record = self.read(path.stem)
            if not record:
                continue
            searchable = " ".join(
                [
                    record.name,
                    record.cwd,
                    record.model,
                    *(str(message.get("content") or "") for message in record.messages),
                ]
            ).casefold()
            if not needle or needle in searchable:
                records.append(record)
        return sorted(records, key=lambda record: record.updated_at, reverse=True)

    def transcript(self, name: str) -> str:
        record = self.read(name)
        if not record:
            raise SessionError(f"Session not found: {name}")
        rows = [
            f"Session: {record.name}",
            f"Workspace: {record.cwd or '(unknown)'}",
            f"Model: {record.model or '(unknown)'}",
            "",
        ]
        for message in record.messages:
            role = str(message.get("role") or "unknown")
            content = str(message.get("content") or "")
            if role == "system":
                continue
            rows.extend([f"## {role}", content or "(empty)", ""])
        return "\n".join(rows).rstrip()

    def _read_data(self, path: Path) -> dict[str, Any]:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise SessionError(f"Could not read session file {path}: {exc}") from exc
        if not isinstance(data, dict):
            raise SessionError(f"Invalid session file: {path}")
        return data

    def save(self, name: str, messages: list[dict[str, Any]], *, cwd: Path, model: str) -> Path:
        self.root.mkdir(parents=True, exist_ok=True)
        path = self.path_for(name)
        payload = {
            "name": name,
            "cwd": str(cwd),
            "model": model,
            "updated_at": int(time.time()),
            "messages": messages,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return path
