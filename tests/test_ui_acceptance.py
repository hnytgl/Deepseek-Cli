"""Exercise the real prompt-toolkit loop with fake models and terminal input."""
from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from prompt_toolkit.input import create_pipe_input
from prompt_toolkit.output import DummyOutput

from deepseek_cli.agent import AgentConfig, DeepSeekAgent
from deepseek_cli.policy import PermissionConfig
from deepseek_cli.session import SessionStore
from deepseek_cli.tools import ToolExecutor
from deepseek_cli import ui


@pytest.mark.parametrize("decision", ["n\n", "/cancel\n", "\x04", "/exit\n"])
def test_fullscreen_pending_approval_reject_cancel_or_exit(monkeypatch, tmp_path: Path, decision):
    class FakeClient:
        model = "fake"
        calls = 0
        def chat(self, payload):
            self.calls += 1
            if self.calls == 1:
                return {"choices": [{"message": {"tool_calls": [{"id": "edit-1", "type": "function", "function": {
                    "name": "write_file", "arguments": json.dumps({"path": "never.txt", "content": "never"})
                }}]}}]}
            return {"choices": [{"message": {"content": "rejected"}}]}

    waiting, ready = threading.Event(), threading.Event()
    statuses = []
    original_status = ui.SplitPaneAgentEvents._set_status
    def set_status(self, text):
        statuses.append(text)
        if text == "waiting for approval":
            waiting.set()
        if text == "ready":
            ready.set()
        original_status(self, text)
    monkeypatch.setattr(ui.SplitPaneAgentEvents, "_set_status", set_status)
    monkeypatch.setattr(SessionStore, "default", classmethod(lambda cls: cls(tmp_path / "sessions")))
    agent = DeepSeekAgent(client=FakeClient(), tools=ToolExecutor(tmp_path, policy=PermissionConfig(approval="ask")),
                         config=AgentConfig(cwd=tmp_path, stream=False))
    failures = []
    application = ui.Application
    with create_pipe_input() as terminal:
        monkeypatch.setattr(ui, "Application", lambda **kwargs: application(input=terminal, output=DummyOutput(), **kwargs))
        def send_input():
            try:
                terminal.send_text("create never.txt\n")
                assert waiting.wait(5), "approval did not appear"
                terminal.send_text("/cost\n")
                terminal.send_text(decision)
                assert ready.wait(5), "worker did not leave the approval wait"
                if decision in {"n\n", "/cancel\n"}:
                    terminal.send_text("/exit\n")
            except Exception as exc:
                failures.append(str(exc))
                terminal.send_text("\x04\x04")
        sender = threading.Thread(target=send_input, daemon=True)
        sender.start()
        assert ui.run_split_pane_interactive(agent, cwd=tmp_path, model="fake") == 0
        sender.join(5)
    assert not failures
    assert not sender.is_alive()
    assert "ready" in statuses
    assert not (tmp_path / "never.txt").exists()
    assert agent.total_requests == (2 if decision == "n\n" else 1)


def test_fullscreen_cancel_discards_earlier_accepted_hunks(monkeypatch, tmp_path: Path):
    class FakeClient:
        model = "fake"
        def chat(self, payload):
            return {"choices": [{"message": {"tool_calls": [{"id": "edit-1", "type": "function", "function": {
                "name": "apply_file_edits", "arguments": json.dumps({"files": [
                    {"path": "first.txt", "content": "after\n"},
                    {"path": "second.txt", "content": "after\n"},
                ]})
            }}]}}]}
    for name in ("first.txt", "second.txt"):
        (tmp_path / name).write_text("before\n", encoding="utf-8")
    waiting = [threading.Event(), threading.Event()]
    ready = threading.Event()
    count = 0
    original_status = ui.SplitPaneAgentEvents._set_status
    def set_status(self, text):
        nonlocal count
        if text == "waiting for approval" and count < len(waiting):
            waiting[count].set()
            count += 1
        if text == "ready":
            ready.set()
        original_status(self, text)
    monkeypatch.setattr(ui.SplitPaneAgentEvents, "_set_status", set_status)
    monkeypatch.setattr(SessionStore, "default", classmethod(lambda cls: cls(tmp_path / "sessions")))
    agent = DeepSeekAgent(client=FakeClient(), tools=ToolExecutor(tmp_path), config=AgentConfig(cwd=tmp_path, stream=False))
    failures = []
    application = ui.Application
    with create_pipe_input() as terminal:
        monkeypatch.setattr(ui, "Application", lambda **kwargs: application(input=terminal, output=DummyOutput(), **kwargs))
        def send_input():
            try:
                terminal.send_text("edit two files\n")
                assert waiting[0].wait(5)
                terminal.send_text("y\n")
                assert waiting[1].wait(5)
                terminal.send_text("/cancel\n")
                assert ready.wait(5)
                terminal.send_text("/exit\n")
            except Exception as exc:
                failures.append(str(exc))
                terminal.send_text("\x04\x04")
        sender = threading.Thread(target=send_input, daemon=True)
        sender.start()
        assert ui.run_split_pane_interactive(agent, cwd=tmp_path, model="fake") == 0
        sender.join(5)
    assert not failures
    assert not sender.is_alive()
    for name in ("first.txt", "second.txt"):
        assert (tmp_path / name).read_text(encoding="utf-8") == "before\n"
