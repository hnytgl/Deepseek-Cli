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
    stream: bool = True


class AgentEventHandler(Protocol):
    def on_step(self, step: int, max_steps: int) -> None: ...

    def on_model_message(self, content: str) -> None: ...

    def on_model_delta(self, content: str) -> None: ...

    def on_reasoning(self, content: str) -> None: ...

    def on_reasoning_delta(self, content: str) -> None: ...

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
            payload = {
                "messages": self.messages,
                "tools": tool_definitions(),
                "tool_choice": "auto",
                "temperature": self.config.temperature,
            }
            message = self._stream_message(payload) if self.config.stream else self._chat_message(payload)
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

    def _chat_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.chat(payload)
        choice = response.get("choices", [{}])[0]
        return choice.get("message") or {}

    def _stream_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, Any]] = {}

        for event in self.client.chat_stream(payload):
            choice = event.get("choices", [{}])[0]
            delta = choice.get("delta") or {}

            content = delta.get("content") or ""
            if content:
                content_parts.append(content)
                if self.events:
                    self.events.on_model_delta(content)

            reasoning = delta.get("reasoning_content") or ""
            if reasoning:
                reasoning_parts.append(reasoning)
                if self.events:
                    self.events.on_reasoning_delta(reasoning)

            for tool_call in delta.get("tool_calls") or []:
                index = int(tool_call.get("index", 0))
                current = tool_call_parts.setdefault(
                    index,
                    {"id": tool_call.get("id"), "type": "function", "function": {"name": "", "arguments": ""}},
                )
                if tool_call.get("id"):
                    current["id"] = tool_call["id"]
                function = tool_call.get("function") or {}
                if function.get("name"):
                    current["function"]["name"] += function["name"]
                if function.get("arguments"):
                    current["function"]["arguments"] += function["arguments"]

        message: dict[str, Any] = {"role": "assistant", "content": "".join(content_parts) or None}
        if reasoning_parts:
            message["reasoning_content"] = "".join(reasoning_parts)
        if tool_call_parts:
            message["tool_calls"] = [tool_call_parts[index] for index in sorted(tool_call_parts)]
        return message

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
