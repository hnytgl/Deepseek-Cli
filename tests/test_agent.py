from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from deepseek_cli.agent import AgentConfig, DeepSeekAgent
from deepseek_cli.tools import ToolExecutor


class FakeClient:
    def __init__(self) -> None:
        self.calls = 0

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        self.calls += 1
        if self.calls == 1:
            return {
                "choices": [
                    {
                        "message": {
                            "role": "assistant",
                            "content": None,
                            "tool_calls": [
                                {
                                    "id": "call_1",
                                    "type": "function",
                                    "function": {
                                        "name": "write_file",
                                        "arguments": json.dumps({"path": "done.txt", "content": "ok"}),
                                    },
                                }
                            ],
                        }
                    }
                ]
            }
        return {"choices": [{"message": {"role": "assistant", "content": "created done.txt"}}]}


def test_agent_executes_tool_loop(tmp_path: Path) -> None:
    agent = DeepSeekAgent(
        client=FakeClient(),  # type: ignore[arg-type]
        tools=ToolExecutor(tmp_path, auto_approve=True),
        config=AgentConfig(cwd=tmp_path, max_steps=4, stream=False),
    )

    answer = agent.run_turn("create a file")

    assert answer == "created done.txt"
    assert (tmp_path / "done.txt").read_text(encoding="utf-8") == "ok"


class StreamingFakeClient:
    def chat_stream(self, payload: dict[str, Any]):
        _ = payload
        yield {"choices": [{"delta": {"content": "hello "}}]}
        yield {"choices": [{"delta": {"content": "stream"}}]}

    def chat(self, payload: dict[str, Any]) -> dict[str, Any]:
        raise AssertionError("streaming path should not call chat")


def test_agent_streams_text(tmp_path: Path) -> None:
    agent = DeepSeekAgent(
        client=StreamingFakeClient(),  # type: ignore[arg-type]
        tools=ToolExecutor(tmp_path, auto_approve=True),
        config=AgentConfig(cwd=tmp_path, max_steps=4, stream=True),
    )

    assert agent.run_turn("say hi") == "hello stream"


def test_agent_trims_context_to_recent_messages(tmp_path: Path) -> None:
    agent = DeepSeekAgent(
        client=FakeClient(),  # type: ignore[arg-type]
        tools=ToolExecutor(tmp_path, auto_approve=True),
        config=AgentConfig(cwd=tmp_path, max_context_chars=500, stream=False),
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": "old" * 1000},
            {"role": "assistant", "content": "recent"},
        ],
    )

    prepared = agent._prepare_messages()

    assert prepared[0]["role"] == "system"
    assert prepared[-1]["content"] == "recent"
    assert all(message.get("content") != "old" * 1000 for message in prepared)


def test_agent_cancel_check_stops_before_request(tmp_path: Path) -> None:
    client = FakeClient()
    agent = DeepSeekAgent(
        client=client,  # type: ignore[arg-type]
        tools=ToolExecutor(tmp_path, auto_approve=True),
        config=AgentConfig(cwd=tmp_path, cancel_check=lambda: True, stream=False),
    )

    assert agent.run_turn("stop") == "Cancelled by user."
    assert client.calls == 0
