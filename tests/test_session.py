from __future__ import annotations

from pathlib import Path

from deepseek_cli.session import SessionStore


def test_session_save_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    messages = [{"role": "system", "content": "hello"}]

    store.save("demo", messages, cwd=tmp_path, model="deepseek-chat")

    assert store.load("demo") == messages
    assert store.load(latest=True) == messages
