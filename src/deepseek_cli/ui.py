from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from rich.align import Align
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.prompt import Confirm, Prompt
from rich.table import Table
from rich.text import Text

from .agent import AgentEventHandler, DeepSeekAgent


def _trim(text: str, limit: int = 5000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... 已截断，原始长度 {len(text)} 字符"


@dataclass
class RichAgentEvents(AgentEventHandler):
    console: Console
    max_log_items: int = 12
    step: int = 0
    max_steps: int = 0
    current_status: str = "等待任务"
    logs: list[tuple[str, str]] = field(default_factory=list)

    def on_step(self, step: int, max_steps: int) -> None:
        self.step = step
        self.max_steps = max_steps
        self.current_status = "请求 DeepSeek"
        self._render()

    def on_model_message(self, content: str) -> None:
        self.current_status = "收到模型回复"
        self._add_log("助手", _trim(content, 1200))
        self._render()

    def on_reasoning(self, content: str) -> None:
        self.current_status = "读取思考内容"
        self._add_log("思考", _trim(content, 1600))
        self._render()

    def on_tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        self.current_status = f"执行工具 {name}"
        self._add_log("工具调用", f"{name} {json.dumps(arguments, ensure_ascii=False)}")
        self._render()

    def on_tool_result(self, name: str, ok: bool, output: str) -> None:
        self.current_status = f"工具 {name} {'完成' if ok else '失败'}"
        self._add_log("工具结果", _trim(output, 2000))
        self._render()

    def _add_log(self, title: str, body: str) -> None:
        self.logs.append((title, body))
        self.logs = self.logs[-self.max_log_items :]

    def _render(self) -> None:
        self.console.clear()
        self.console.print(render_header(self.step, self.max_steps, self.current_status))
        for title, body in self.logs:
            style = "cyan" if title in {"工具调用", "工具结果"} else "magenta" if title == "思考" else "green"
            self.console.print(Panel(body, title=title, border_style=style))


def render_header(step: int, max_steps: int, status: str) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(ratio=2)
    table.add_column(ratio=3)
    step_text = f"{step}/{max_steps}" if max_steps else "0/0"
    progress = Progress(
        TextColumn("[bold]进度[/bold]"),
        BarColumn(bar_width=None),
        TextColumn(step_text),
        expand=True,
    )
    task = progress.add_task("agent", total=max_steps or 1, completed=step)
    progress.update(task, completed=step)
    table.add_row(Text("DeepSeek Codex CLI", style="bold cyan"), Text(status, style="bold"))
    table.add_row("", progress)
    return Panel(table, border_style="cyan")


def print_welcome(console: Console, cwd: Path, model: str) -> None:
    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("工作区", str(cwd))
    body.add_row("模型", model)
    body.add_row("命令", "/exit 退出, /clear 清空上下文, /help 帮助")
    console.print(Panel(body, title="DeepSeek CLI", border_style="cyan"))


def print_help(console: Console) -> None:
    console.print(
        Panel(
            "/exit 或 /quit：退出\n"
            "/clear：清空当前对话上下文\n"
            "/help：显示帮助\n\n"
            "直接输入任务即可，例如：\n"
            "  帮我阅读这个项目并修复测试\n"
            "  给当前仓库补 README 和单元测试",
            title="帮助",
            border_style="cyan",
        )
    )


def run_rich_interactive(agent: DeepSeekAgent, *, cwd: Path, model: str) -> int:
    console = Console()
    events = RichAgentEvents(console)
    agent.events = events
    print_welcome(console, cwd, model)

    while True:
        try:
            prompt = Prompt.ask("\n[bold cyan]深问[/bold cyan]").strip()
        except (EOFError, KeyboardInterrupt):
            console.print()
            return 0

        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            return 0
        if prompt == "/help":
            print_help(console)
            continue
        if prompt == "/clear":
            agent.messages.clear()
            agent.__post_init__()
            events.logs.clear()
            events.step = 0
            events.max_steps = 0
            events.current_status = "上下文已清空"
            events._render()
            continue

        answer = agent.run_turn(prompt)
        console.print(Panel(Markdown(answer or "任务完成。"), title="最终回复", border_style="green"))


class RichToolConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, prompt: str) -> bool:
        return Confirm.ask(f"[yellow]{prompt}[/yellow]", default=False, console=self.console)
