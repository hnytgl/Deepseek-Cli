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
        config=AgentConfig(cwd=tmp_path, max_steps=4),
    )

    answer = agent.run_turn("create a file")

    assert answer == "created done.txt"
    assert (tmp_path / "done.txt").read_text(encoding="utf-8") == "ok"
