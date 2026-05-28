from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from prompt_toolkit import Application, PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.filters import Condition
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit, Window
from prompt_toolkit.layout.controls import BufferControl, FormattedTextControl
from prompt_toolkit.layout.dimension import Dimension
from prompt_toolkit.widgets import Box, Frame, TextArea
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .agent import AgentEventHandler, DeepSeekAgent
from .patch_review import PatchHunk
from .session import default_session_dir


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
    streaming_answer: str = ""
    streaming_reasoning: str = ""
    logs: list[tuple[str, str]] = field(default_factory=list)

    def on_step(self, step: int, max_steps: int) -> None:
        self.step = step
        self.max_steps = max_steps
        self.current_status = "请求 DeepSeek"
        self.streaming_answer = ""
        self.streaming_reasoning = ""
        self._render()

    def on_model_delta(self, content: str) -> None:
        self.current_status = "流式输出回复"
        self.streaming_answer += content
        self._render()

    def on_model_message(self, content: str) -> None:
        self.current_status = "收到模型回复"
        if not self.streaming_answer:
            self._add_log("助手", _trim(content, 1200))
        self._render()

    def on_reasoning_delta(self, content: str) -> None:
        self.current_status = "流式输出思考"
        self.streaming_reasoning += content
        self._render()

    def on_reasoning(self, content: str) -> None:
        self.current_status = "读取思考内容"
        if not self.streaming_reasoning:
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
        if self.streaming_reasoning:
            self.console.print(Panel(_trim(self.streaming_reasoning, 1600), title="思考", border_style="magenta"))
        if self.streaming_answer:
            self.console.print(Panel(Markdown(_trim(self.streaming_answer, 2200)), title="回复草稿", border_style="green"))
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


def print_welcome(console: Console, cwd: Path, model: str, session_name: str | None) -> None:
    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("工作区", str(cwd))
    body.add_row("模型", model)
    body.add_row("会话", session_name or "未持久化")
    body.add_row("命令", "/exit 退出, /clear 清空上下文, /help 帮助")
    console.print(Panel(body, title="DeepSeek CLI", border_style="cyan"))


def print_help(console: Console) -> None:
    console.print(
        Panel(
            "/exit 或 /quit：退出\n"
            "/clear：清空当前对话上下文\n"
            "/logs：用可滚动 pager 查看本轮日志\n"
            "/review：查看当前 Git 多文件 diff\n"
            "/help：显示帮助\n\n"
            "快捷键：Ctrl+D 退出，Ctrl+L 清屏，方向键浏览历史。\n\n"
            "直接输入任务即可，例如：\n"
            "  帮我阅读这个项目并修复测试\n"
            "  创建分支，完成修改，提交并打开 PR",
            title="帮助",
            border_style="cyan",
        )
    )


def make_prompt_session() -> PromptSession[str]:
    history_path = default_session_dir().parent / "prompt_history.txt"
    history_path.parent.mkdir(parents=True, exist_ok=True)
    bindings = KeyBindings()

    @bindings.add("c-l")
    def _(event) -> None:
        event.app.renderer.clear()

    @bindings.add("c-d")
    def _(event) -> None:
        event.app.exit(exception=EOFError)

    return PromptSession(history=FileHistory(str(history_path)), key_bindings=bindings)


def show_logs(console: Console, events: RichAgentEvents) -> None:
    with console.pager(styles=True):
        console.print(render_header(events.step, events.max_steps, events.current_status))
        if events.streaming_reasoning:
            console.print(Panel(events.streaming_reasoning, title="思考", border_style="magenta"))
        if events.streaming_answer:
            console.print(Panel(Markdown(events.streaming_answer), title="回复草稿", border_style="green"))
        for title, body in events.logs:
            console.print(Panel(body, title=title))


def show_git_review(console: Console, cwd: Path) -> None:
    completed = subprocess.run(
        ["git", "diff", "--", "."],
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    diff = completed.stdout or completed.stderr or "当前没有 Git diff。"
    with console.pager(styles=True):
        console.print(Panel(Syntax(diff, "diff", word_wrap=True), title="多文件 Review", border_style="yellow"))


def run_rich_interactive(
    agent: DeepSeekAgent,
    *,
    cwd: Path,
    model: str,
    session_name: str | None = None,
    on_turn_done: Callable[[], None] | None = None,
    fullscreen: bool = False,
) -> int:
    console = Console()
    events = RichAgentEvents(console)
    agent.events = events
    if fullscreen:
        with console.screen(style="none"):
            return _run_loop(console, events, agent, cwd, model, session_name, on_turn_done)
    return _run_loop(console, events, agent, cwd, model, session_name, on_turn_done)


def _run_loop(
    console: Console,
    events: RichAgentEvents,
    agent: DeepSeekAgent,
    cwd: Path,
    model: str,
    session_name: str | None,
    on_turn_done: Callable[[], None] | None,
) -> int:
    print_welcome(console, cwd, model, session_name)
    prompt_session = make_prompt_session()

    while True:
        try:
            prompt = prompt_session.prompt("\n深问> ").strip()
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
        if prompt == "/logs":
            show_logs(console, events)
            continue
        if prompt == "/review":
            show_git_review(console, cwd)
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
        if on_turn_done:
            on_turn_done()
        console.print(Panel(Markdown(answer or "任务完成。"), title="最终回复", border_style="green"))


class RichToolConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, prompt: str) -> bool:
        return Confirm.ask(f"[yellow]{prompt}[/yellow]", default=False, console=self.console)


class RichDiffConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, prompt: str, diff: str) -> bool:
        self.console.print(Panel(Syntax(diff, "diff", word_wrap=True), title="文件变更预览", border_style="yellow"))
        return Confirm.ask(f"[yellow]{prompt}[/yellow]", default=False, console=self.console)


class RichFileEditConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, items: list[tuple[Path, str]]) -> list[bool]:
        accepted: list[bool] = []
        for path, diff in items:
            self.console.print(Panel(Syntax(diff, "diff", word_wrap=True), title=f"Review {path}", border_style="yellow"))
            accepted.append(Confirm.ask(f"[yellow]Apply this file edit? {path}[/yellow]", default=False, console=self.console))
        return accepted


class RichHunkConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, hunks: list[PatchHunk]) -> list[bool]:
        accepted: list[bool] = []
        for index, hunk in enumerate(hunks, start=1):
            self.console.print(Panel(Syntax(hunk.diff, "diff", word_wrap=True), title=f"Hunk {index}: {hunk.path}", border_style="yellow"))
            accepted.append(Confirm.ask(f"[yellow]Apply this hunk? {hunk.path} #{index}[/yellow]", default=False, console=self.console))
        return accepted


@dataclass
class SplitPaneAgentEvents(AgentEventHandler):
    app: Application | None = None
    status: TextArea | None = None
    logs: TextArea | None = None
    answer: TextArea | None = None
    reasoning: TextArea | None = None
    step: int = 0
    max_steps: int = 0

    def bind(self, app: Application, status: TextArea, logs: TextArea, answer: TextArea, reasoning: TextArea) -> None:
        self.app = app
        self.status = status
        self.logs = logs
        self.answer = answer
        self.reasoning = reasoning

    def on_step(self, step: int, max_steps: int) -> None:
        self.step = step
        self.max_steps = max_steps
        self._set_status("Requesting DeepSeek")
        if self.answer:
            self.answer.text = ""
        if self.reasoning:
            self.reasoning.text = ""
        self._invalidate()

    def on_model_delta(self, content: str) -> None:
        if self.answer:
            self.answer.text += content
        self._set_status("Streaming answer")
        self._invalidate()

    def on_model_message(self, content: str) -> None:
        if self.answer and not self.answer.text:
            self.answer.text = content
        self._set_status("Received answer")
        self._invalidate()

    def on_reasoning_delta(self, content: str) -> None:
        if self.reasoning:
            self.reasoning.text += content
        self._set_status("Streaming reasoning")
        self._invalidate()

    def on_reasoning(self, content: str) -> None:
        if self.reasoning and not self.reasoning.text:
            self.reasoning.text = content
        self._set_status("Received reasoning")
        self._invalidate()

    def on_tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        self._append_log(f"[tool] {name} {json.dumps(arguments, ensure_ascii=False)}")
        self._set_status(f"Running tool {name}")
        self._invalidate()

    def on_tool_result(self, name: str, ok: bool, output: str) -> None:
        self._append_log(f"[{name} {'ok' if ok else 'error'}]\n{_trim(output, 3000)}")
        self._set_status(f"Tool {name} {'completed' if ok else 'failed'}")
        self._invalidate()

    def _set_status(self, text: str) -> None:
        if self.status:
            self.status.text = f"DeepSeek Codex CLI | {text} | step {self.step}/{self.max_steps}"

    def _append_log(self, text: str) -> None:
        if self.logs:
            self.logs.text = (self.logs.text + "\n\n" + text).strip()

    def _invalidate(self) -> None:
        if self.app:
            self.app.invalidate()


def run_split_pane_interactive(
    agent: DeepSeekAgent,
    *,
    cwd: Path,
    model: str,
    session_name: str | None = None,
    on_turn_done: Callable[[], None] | None = None,
) -> int:
    events = SplitPaneAgentEvents()
    agent.events = events
    status = TextArea(text=f"DeepSeek Codex CLI | {cwd} | {model} | {session_name or 'no session'}", height=1, focusable=False)
    logs = TextArea(text="Logs will appear here. Mouse wheel scrolls focused panes.", scrollbar=True, focusable=True, wrap_lines=False)
    answer = TextArea(text="", scrollbar=True, focusable=True, wrap_lines=True)
    reasoning = TextArea(text="", scrollbar=True, focusable=True, wrap_lines=True)
    input_box = TextArea(height=3, prompt="深问> ", multiline=False)
    bindings = KeyBindings()

    @bindings.add("c-d")
    def _(event) -> None:
        event.app.exit(result=0)

    @bindings.add("c-l")
    def _(event) -> None:
        logs.text = ""
        answer.text = ""
        reasoning.text = ""
        event.app.invalidate()

    @bindings.add("tab")
    def _(event) -> None:
        event.app.layout.focus_next()

    def submit(_: Buffer) -> bool:
        prompt = input_box.text.strip()
        input_box.text = ""
        if not prompt:
            return True
        if prompt in {"/exit", "/quit"}:
            app.exit(result=0)
            return True
        if prompt == "/clear":
            agent.messages.clear()
            agent.__post_init__()
            logs.text = ""
            answer.text = ""
            reasoning.text = ""
            return True
        if prompt == "/review":
            completed = subprocess.run(["git", "diff", "--", "."], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
            logs.text = completed.stdout or completed.stderr or "No git diff."
            return True
        result = agent.run_turn(prompt)
        answer.text = result or answer.text
        if on_turn_done:
            on_turn_done()
        return True

    input_box.buffer.accept_handler = submit
    body = HSplit(
        [
            status,
            VSplit(
                [
                    Frame(logs, title="Logs"),
                    HSplit([Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")]),
                ]
            ),
            Frame(input_box, title="Input"),
        ]
    )
    app = Application(layout=Layout(body, focused_element=input_box), key_bindings=bindings, full_screen=True, mouse_support=True)
    events.bind(app, status, logs, answer, reasoning)
    return int(app.run() or 0)
