from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Protocol

from .api import DeepSeekClient
from .tools import ToolExecutor, tool_definitions


SYSTEM_PROMPT = """You are DeepSeek CLI, an autonomous command-line coding agent.
You help users inspect, modify, test, and explain software projects.

Working rules:
- Use tools whenever local files, command output, or tests are needed.
- Before editing, inspect the relevant files.
- Prefer small, targeted changes that fit the existing project.
- After code changes, run the most relevant checks available.
- Keep final answers concise and include changed files and verification.
- Never claim a command passed unless a tool result confirms it.
- When useful, briefly explain current progress before calling tools.
"""


@dataclass
class AgentConfig:
    cwd: Path
    max_steps: int = 24
    temperature: float = 0.2


class AgentEventHandler(Protocol):
    def on_step(self, step: int, max_steps: int) -> None: ...

    def on_model_message(self, content: str) -> None: ...

    def on_reasoning(self, content: str) -> None: ...

    def on_tool_start(self, name: str, arguments: dict[str, Any]) -> None: ...

    def on_tool_result(self, name: str, ok: bool, output: str) -> None: ...


@dataclass
class DeepSeekAgent:
    client: DeepSeekClient
    tools: ToolExecutor
    config: AgentConfig
    events: AgentEventHandler | None = None
    messages: list[dict[str, Any]] = field(default_factory=list)

    def __post_init__(self) -> None:
        if not self.messages:
            self.messages.append({"role": "system", "content": SYSTEM_PROMPT})

    def run_turn(self, user_text: str) -> str:
        self.messages.append(
            {
                "role": "user",
                "content": f"Workspace: {self.config.cwd}\n\n{user_text}",
            }
        )

        final_text = ""
        for step in range(1, self.config.max_steps + 1):
            if self.events:
                self.events.on_step(step, self.config.max_steps)
            response = self.client.chat(
                {
                    "messages": self.messages,
                    "tools": tool_definitions(),
                    "tool_choice": "auto",
                    "temperature": self.config.temperature,
                }
            )
            choice = response.get("choices", [{}])[0]
            message = choice.get("message") or {}
            self.messages.append(self._normalize_assistant_message(message))

            content = message.get("content") or ""
            reasoning = message.get("reasoning_content") or ""
            if reasoning and self.events:
                self.events.on_reasoning(reasoning)
            if content:
                final_text = content
                if self.events:
                    self.events.on_model_message(content)

            tool_calls = message.get("tool_calls") or []
            if not tool_calls:
                return content or final_text

            for tool_call in tool_calls:
                tool_message = self._execute_tool_call(tool_call)
                self.messages.append(tool_message)

        return "Stopped because max tool steps were reached. Please retry with a narrower request."

    def _normalize_assistant_message(self, message: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {"role": "assistant"}
        if message.get("content") is not None:
            normalized["content"] = message.get("content")
        if message.get("tool_calls"):
            normalized["tool_calls"] = message["tool_calls"]
        return normalized

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function") or {}
        name = function.get("name") or ""
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError:
            arguments = {}

        if self.events:
            self.events.on_tool_start(name, arguments)
        else:
            print(f"\n[tool] {name} {json.dumps(arguments, ensure_ascii=False)}")
        result = self.tools.run(name, arguments)
        if self.events:
            self.events.on_tool_result(name, result.ok, result.output)
        else:
            print(result.output[:4000])
            if len(result.output) > 4000:
                print("[tool output truncated in terminal]")

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id"),
            "content": result.to_content(),
        }
