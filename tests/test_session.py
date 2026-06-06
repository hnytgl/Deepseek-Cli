from __future__ import annotations

from pathlib import Path

import pytest

from deepseek_cli.session import SessionError, SessionStore


def test_session_save_and_load(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    messages = [{"role": "system", "content": "hello"}]

    store.save("demo", messages, cwd=tmp_path, model="deepseek-chat")

    assert store.load("demo") == messages
    assert store.load(latest=True) == messages


def test_invalid_session_has_clear_error(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.path_for("broken").write_text("{", encoding="utf-8")

    with pytest.raises(SessionError, match="Could not read session file"):
        store.load("broken")


def test_session_rejects_invalid_messages(tmp_path: Path) -> None:
    store = SessionStore(tmp_path)
    store.path_for("broken").write_text('{"messages": [1]}', encoding="utf-8")

    with pytest.raises(SessionError, match="Invalid messages"):
        store.load("broken")
