from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any


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

    def load(self, name: str | None = None, *, latest: bool = False) -> list[dict[str, Any]]:
        path = self.latest_path() if latest else self.path_for(name or "default")
        if not path or not path.exists():
            return []
        data = json.loads(path.read_text(encoding="utf-8"))
        messages = data.get("messages", [])
        return messages if isinstance(messages, list) else []

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
