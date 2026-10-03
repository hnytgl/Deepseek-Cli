from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .api import DeepSeekAPIError, DeepSeekClient
from .tools import ToolExecutor, ToolResult, tool_definitions


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
- For large files, read them page by page with read_file offset/limit.
- If read_file returns has_more=true, continue with next_offset when the missing content matters.
- Do not repeatedly read the same truncated page; advance offset, narrow the range, or use search.
- Prefer the search tool over shell grep/rg for code searching (faster, no shell needed).
- Prefer patch_file over write_file for small edits (saves tokens, reduces hallucination risk).
"""


def build_system_prompt(agents_md: str = "") -> str:
    """Build the system prompt, optionally appending project instructions from AGENTS.md."""
    prompt = SYSTEM_PROMPT
    if agents_md:
        prompt += (
            "\n\n---\n"
            "Project instructions (from AGENTS.md):\n\n"
            f"{agents_md}\n"
        )
    return prompt


@dataclass
class AgentConfig:
    cwd: Path
    max_steps: int = 128
    max_context_chars: int = 200_000  # ~50-70K tokens, safe for 64K-128K models
    temperature: float = 0.2
    stream: bool = True
    thinking_budget: int = 4096  # max thinking tokens for reasoning mode
    quiet: bool = False
    cancel_check: Callable[[], bool] | None = None


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
    agents_md: str = ""  # project instructions from AGENTS.md
    # Usage tracking for /cost command
    total_prompt_tokens: int = field(default=0, init=False)
    total_completion_tokens: int = field(default=0, init=False)
    total_requests: int = field(default=0, init=False)

    def __post_init__(self) -> None:
        # Direct API callers may supply a custom system prompt. Session restore
        # removes saved system messages before this method is called.
        if not self.agents_md and self.messages and self.messages[0].get("role") == "system":
            return
        history = [message for message in self.messages if message.get("role") != "system"]
        self.messages = [{"role": "system", "content": build_system_prompt(self.agents_md)}, *history]

    def restore_messages(self, messages: list[dict[str, Any]]) -> None:
        from .config import _load_agents_md

        self.agents_md = _load_agents_md(self.config.cwd)
        self.messages = [message for message in messages if message.get("role") != "system"]
        self.__post_init__()

    def get_usage_summary(self) -> str:
        """Return a human-readable summary of token usage for /cost command."""
        total = self.total_prompt_tokens + self.total_completion_tokens
        # DeepSeek pricing (approximate, per 1M tokens):
        # deepseek-flash / deepseek-v4-flash: input ¥1 / output ¥2
        # deepseek-v4-pro (thinking mode): input ¥4 / output ¥16
        model = getattr(self.client, "model", "") or "unknown"
        if "pro" in model.lower() or "reasoner" in model.lower():
            cost = (self.total_prompt_tokens * 4 + self.total_completion_tokens * 16) / 1_000_000
        else:
            cost = (self.total_prompt_tokens * 1 + self.total_completion_tokens * 2) / 1_000_000
        return (
            f"Requests: {self.total_requests}\n"
            f"Prompt tokens: {self.total_prompt_tokens:,}\n"
            f"Completion tokens: {self.total_completion_tokens:,}\n"
            f"Total tokens: {total:,}\n"
            f"Estimated cost: ¥{cost:.4f} ({model})"
        )

    def run_turn(self, user_text: str) -> str:
        self.messages.append(
            {
                "role": "user",
                "content": f"Workspace: {self.config.cwd}\n\n{user_text}",
            }
        )

        final_text = ""
        for step in range(1, self.config.max_steps + 1):
            if self._cancelled():
                return "Cancelled by user."
            if self.events:
                self.events.on_step(step, self.config.max_steps)
            payload = {
                "messages": self._prepare_messages(),
                "tools": tool_definitions(),
                "tool_choice": "auto",
                "temperature": self.config.temperature,
            }
            # DeepSeek reasoning mode: pass thinking budget when using pro/thinking model
            _model = (getattr(self.client, "model", "") or "").lower()
            if "pro" in _model or "reasoner" in _model or "thinking" in _model:
                payload["thinking"] = {"type": "enabled", "budget_tokens": self.config.thinking_budget}
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

            # Concurrent execution for read-only tools, serial for write tools
            from .tools_registry import READ_ONLY_TOOLS
            read_only_calls = []
            write_calls = []
            for tc in tool_calls:
                fn_name = (tc.get("function") or {}).get("name", "")
                if fn_name in READ_ONLY_TOOLS:
                    read_only_calls.append(tc)
                else:
                    write_calls.append(tc)

            # Execute read-only tools concurrently
            if len(read_only_calls) > 1:
                from concurrent.futures import ThreadPoolExecutor, as_completed
                with ThreadPoolExecutor(max_workers=min(4, len(read_only_calls))) as pool:
                    futures = {pool.submit(self._execute_tool_call, tc): tc for tc in read_only_calls}
                    results = {}
                    for future in as_completed(futures):
                        tc = futures[future]
                        results[id(tc)] = future.result()
                # Append in original order
                for tc in read_only_calls:
                    self.messages.append(results[id(tc)])
            else:
                for tc in read_only_calls:
                    if self._cancelled():
                        return "Cancelled by user."
                    self.messages.append(self._execute_tool_call(tc))

            # Execute write tools serially (order matters)
            for tc in write_calls:
                if self._cancelled():
                    return "Cancelled by user."
                self.messages.append(self._execute_tool_call(tc))

        return "Stopped because max tool steps were reached. Please retry with a narrower request."

    def _cancelled(self) -> bool:
        return bool(self.config.cancel_check and self.config.cancel_check())

    def _prepare_messages(self) -> list[dict[str, Any]]:
        budget = max(1, self.config.max_context_chars)
        if not self.messages:
            return []

        system = self.messages[0] if self.messages[0].get("role") == "system" else None
        history = self.messages[1:] if system else self.messages
        prepared: list[dict[str, Any]] = []
        used = self._message_size(system) if system else 0

        for message in reversed(history):
            size = self._message_size(message)
            if prepared and used + size > budget:
                break
            if not prepared and used + size > budget:
                prepared.append(self._shrink_message(message, max(1, budget - used)))
                break
            prepared.append(message)
            used += size

        prepared.reverse()
        while prepared and prepared[0].get("role") == "tool":
            prepared.pop(0)
        return ([system] if system else []) + prepared

    def _message_size(self, message: dict[str, Any] | None) -> int:
        if not message:
            return 0
        return len(json.dumps(message, ensure_ascii=False))

    def _shrink_message(self, message: dict[str, Any], budget: int) -> dict[str, Any]:
        shrunk = dict(message)
        content = str(shrunk.get("content") or "")
        marker = "\n\n[content trimmed to fit context budget]"
        allowed = max(0, budget - self._message_size({**shrunk, "content": marker}))
        shrunk["content"] = content[-allowed:] + marker if allowed else marker
        return shrunk

    def _chat_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        response = self.client.chat(payload)
        # Track usage for /cost command
        usage = response.get("usage")
        if isinstance(usage, dict):
            self.total_prompt_tokens += int(usage.get("prompt_tokens") or 0)
            self.total_completion_tokens += int(usage.get("completion_tokens") or 0)
        self.total_requests += 1
        choices = response.get("choices")
        if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
            raise DeepSeekAPIError("DeepSeek API response did not include a valid choice.")
        message = choices[0].get("message")
        if not isinstance(message, dict):
            raise DeepSeekAPIError("DeepSeek API response did not include a valid message.")
        return message

    def _stream_message(self, payload: dict[str, Any]) -> dict[str, Any]:
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, Any]] = {}
        final_usage: dict[str, Any] | None = None

        for event in self.client.chat_stream(payload):
            # Track usage from final streaming chunk (DeepSeek sends usage in last event)
            usage = event.get("usage")
            if isinstance(usage, dict):
                final_usage = usage
            choices = event.get("choices")
            if not isinstance(choices, list) or not choices or not isinstance(choices[0], dict):
                continue
            choice = choices[0]
            delta = choice.get("delta") or {}
            if not isinstance(delta, dict):
                continue

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
        if final_usage is not None:
            self.total_prompt_tokens += int(final_usage.get("prompt_tokens") or 0)
            self.total_completion_tokens += int(final_usage.get("completion_tokens") or 0)
        self.total_requests += 1
        return message

    def _normalize_assistant_message(self, message: dict[str, Any]) -> dict[str, Any]:
        normalized: dict[str, Any] = {"role": "assistant"}
        if message.get("content") is not None:
            normalized["content"] = message.get("content")
        if message.get("tool_calls"):
            normalized["tool_calls"] = message["tool_calls"]
        if message.get("reasoning_content") is not None:
            normalized["reasoning_content"] = message["reasoning_content"]
        return normalized

    def _execute_tool_call(self, tool_call: dict[str, Any]) -> dict[str, Any]:
        function = tool_call.get("function") or {}
        name = function.get("name") or ""
        raw_arguments = function.get("arguments") or "{}"
        try:
            arguments = json.loads(raw_arguments)
        except json.JSONDecodeError as exc:
            snippet = str(raw_arguments)[:500]
            result = {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": ToolResult(
                    False,
                    f"Invalid tool JSON arguments for {name}: {exc.msg}. Raw arguments: {snippet}",
                ).to_content(),
            }
            if self.events:
                self.events.on_tool_start(name, {})
                self.events.on_tool_result(name, False, json.loads(result["content"])["output"])
            return result
        if not isinstance(arguments, dict):
            result = ToolResult(
                False,
                f"Invalid tool JSON arguments for {name}: expected an object, got {type(arguments).__name__}.",
            )
            if self.events:
                self.events.on_tool_start(name, {})
                self.events.on_tool_result(name, False, result.output)
            return {
                "role": "tool",
                "tool_call_id": tool_call.get("id"),
                "content": result.to_content(),
            }

        if self.events:
            self.events.on_tool_start(name, arguments)
        elif not self.config.quiet:
            print(f"\n[tool] {name} {json.dumps(arguments, ensure_ascii=False)}")
        result = self.tools.run(name, arguments)
        if self.events:
            self.events.on_tool_result(name, result.ok, result.output)
        elif not self.config.quiet:
            print(result.output[:4000])
            if len(result.output) > 4000:
                print("[tool output truncated in terminal]")

        return {
            "role": "tool",
            "tool_call_id": tool_call.get("id"),
            "content": result.to_content(),
        }
