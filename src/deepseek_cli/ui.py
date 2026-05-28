from __future__ import annotations

import json
import os
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from prompt_toolkit import Application, PromptSession
from prompt_toolkit.buffer import Buffer
from prompt_toolkit.history import FileHistory
from prompt_toolkit.key_binding import KeyBindings
from prompt_toolkit.layout import HSplit, Layout, VSplit
from prompt_toolkit.widgets import Frame, TextArea
from rich.console import Console
from rich.markdown import Markdown
from rich.panel import Panel
from rich.progress import BarColumn, Progress, TextColumn
from rich.prompt import Confirm, Prompt
from rich.syntax import Syntax
from rich.table import Table
from rich.text import Text

from .agent import AgentEventHandler, DeepSeekAgent
from .patch_review import HunkDecision, PatchHunk
from .session import default_session_dir


def _trim(text: str, limit: int = 5000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated, original length {len(text)} chars"


def summarize_tool_output(name: str, ok: bool, output: str) -> str:
    lines = output.splitlines()
    first = lines[0] if lines else "(no output)"
    return f"{first}\n{len(output)} chars captured. Use /logs, /expand, or F4 to open full output."


@dataclass
class RichAgentEvents(AgentEventHandler):
    console: Console
    max_log_items: int = 12
    compact: bool = True
    step: int = 0
    max_steps: int = 0
    current_status: str = "Waiting"
    streaming_answer: str = ""
    streaming_reasoning: str = ""
    logs: list[tuple[str, str]] = field(default_factory=list)

    def on_step(self, step: int, max_steps: int) -> None:
        self.step = step
        self.max_steps = max_steps
        self.current_status = "Requesting DeepSeek"
        self.streaming_answer = ""
        self.streaming_reasoning = ""
        self._render()

    def on_model_delta(self, content: str) -> None:
        self.current_status = "Streaming answer"
        self.streaming_answer += content
        self._render()

    def on_model_message(self, content: str) -> None:
        self.current_status = "Answer received"
        if not self.streaming_answer:
            self._add_log("assistant", content)
        self._render()

    def on_reasoning_delta(self, content: str) -> None:
        self.current_status = "Streaming reasoning"
        self.streaming_reasoning += content
        self._render()

    def on_reasoning(self, content: str) -> None:
        self.current_status = "Reasoning received"
        if not self.streaming_reasoning:
            self._add_log("reasoning", content)
        self._render()

    def on_tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        self.current_status = f"Running {name}"
        self._add_log("tool call", f"{name} {json.dumps(arguments, ensure_ascii=False)}")
        self._render()

    def on_tool_result(self, name: str, ok: bool, output: str) -> None:
        self.current_status = f"{name} {'ok' if ok else 'failed'}"
        self._add_log("tool result", output)
        self._render()

    def _add_log(self, title: str, body: str) -> None:
        self.logs.append((title, body))
        self.logs = self.logs[-self.max_log_items :]

    def _render(self) -> None:
        self.console.clear()
        self.console.print(render_header(self.step, self.max_steps, self.current_status))
        if self.streaming_reasoning:
            self.console.print(Panel(_trim(self.streaming_reasoning, 300 if self.compact else 1600), title="reasoning", border_style="magenta"))
        if self.streaming_answer:
            self.console.print(Panel(Markdown(_trim(self.streaming_answer, 700 if self.compact else 2200)), title="answer draft", border_style="green"))
        for title, body in self.logs:
            style = "cyan" if title.startswith("tool") else "magenta" if title == "reasoning" else "green"
            rendered = summarize_tool_output(title, True, body) if self.compact and title == "tool result" else _trim(body, 500 if self.compact else 5000)
            self.console.print(Panel(rendered, title=title, border_style=style))


def render_header(step: int, max_steps: int, status: str) -> Panel:
    table = Table.grid(expand=True)
    table.add_column(ratio=2)
    table.add_column(ratio=3)
    step_text = f"{step}/{max_steps}" if max_steps else "0/0"
    progress = Progress(TextColumn("[bold]progress[/bold]"), BarColumn(bar_width=None), TextColumn(step_text), expand=True)
    task = progress.add_task("agent", total=max_steps or 1, completed=step)
    progress.update(task, completed=step)
    table.add_row(Text("DeepSeek Codex CLI", style="bold cyan"), Text(status, style="bold"))
    table.add_row("", progress)
    return Panel(table, border_style="cyan")


def print_welcome(console: Console, cwd: Path, model: str, session_name: str | None) -> None:
    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("workspace", str(cwd))
    body.add_row("model", model)
    body.add_row("session", session_name or "none")
    body.add_row("commands", "/exit, /clear, /help, /logs, /review, /compact, /expand")
    console.print(Panel(body, title="DeepSeek CLI", border_style="cyan"))


def print_help(console: Console) -> None:
    console.print(
        Panel(
            "/exit or /quit: exit\n"
            "/clear: clear conversation\n"
            "/logs: open full logs in a pager\n"
            "/review: show current git diff\n"
            "/compact: compact Codex-like output\n"
            "/expand: full output mode\n"
            "/help: show help\n\n"
            "Fullscreen keys: F4 toggles compact/full logs, Tab changes focus, Ctrl+L clears panes, Ctrl+D exits.",
            title="help",
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
            console.print(Panel(events.streaming_reasoning, title="reasoning", border_style="magenta"))
        if events.streaming_answer:
            console.print(Panel(Markdown(events.streaming_answer), title="answer", border_style="green"))
        for title, body in events.logs:
            console.print(Panel(body, title=title))


def show_git_review(console: Console, cwd: Path) -> None:
    completed = subprocess.run(["git", "diff", "--", "."], cwd=cwd, text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=60)
    diff = completed.stdout or completed.stderr or "No git diff."
    with console.pager(styles=True):
        console.print(Panel(Syntax(diff, "diff", word_wrap=True), title="review", border_style="yellow"))


def run_rich_interactive(
    agent: DeepSeekAgent,
    *,
    cwd: Path,
    model: str,
    session_name: str | None = None,
    on_turn_done: Callable[[], None] | None = None,
    fullscreen: bool = False,
    compact: bool = True,
) -> int:
    console = Console()
    events = RichAgentEvents(console, compact=compact)
    agent.events = events
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
            prompt = prompt_session.prompt("\nDeepSeek> ").strip()
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
        if prompt == "/compact":
            events.compact = True
            events._render()
            continue
        if prompt == "/expand":
            events.compact = False
            events._render()
            continue
        if prompt == "/clear":
            agent.messages.clear()
            agent.__post_init__()
            events.logs.clear()
            events.step = 0
            events.max_steps = 0
            events.current_status = "cleared"
            events._render()
            continue

        answer = agent.run_turn(prompt)
        if on_turn_done:
            on_turn_done()
        console.print(Panel(Markdown(answer or "Done."), title="final", border_style="green"))


class RichToolConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, prompt: str) -> bool:
        return Confirm.ask(f"[yellow]{prompt}[/yellow]", default=False, console=self.console)


class RichDiffConfirmer:
    def __init__(self, console: Console | None = None) -> None:
        self.console = console or Console()

    def __call__(self, prompt: str, diff: str) -> bool:
        self.console.print(Panel(Syntax(diff, "diff", word_wrap=True), title="file change preview", border_style="yellow"))
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

    def __call__(self, hunks: list[PatchHunk]) -> list[HunkDecision]:
        accepted: list[HunkDecision] = []
        for index, hunk in enumerate(hunks, start=1):
            self.console.print(Panel(Syntax(hunk.diff, "diff", word_wrap=True), title=f"Hunk {index}: {hunk.path}", border_style="yellow"))
            choice = Prompt.ask(
                f"[yellow]Hunk {index}: accept, reject, edit[/yellow]",
                choices=["a", "r", "e", "accept", "reject", "edit"],
                default="r",
                console=self.console,
            )
            if choice in {"a", "accept"}:
                accepted.append(True)
            elif choice in {"e", "edit"}:
                accepted.append(edit_hunk_text(hunk))
            else:
                accepted.append(False)
        return accepted


def edit_hunk_text(hunk: PatchHunk) -> str:
    editor = os.environ.get("EDITOR") or ("notepad" if os.name == "nt" else "vi")
    suffix = hunk.path.suffix or ".txt"
    with tempfile.NamedTemporaryFile("w+", suffix=suffix, delete=False, encoding="utf-8") as handle:
        temp_path = Path(handle.name)
        handle.write(hunk.new_text)
    try:
        subprocess.run([editor, str(temp_path)], check=False)
        return temp_path.read_text(encoding="utf-8")
    finally:
        try:
            temp_path.unlink()
        except OSError:
            pass


@dataclass
class SplitPaneAgentEvents(AgentEventHandler):
    app: Application | None = None
    status: TextArea | None = None
    logs: TextArea | None = None
    answer: TextArea | None = None
    reasoning: TextArea | None = None
    step: int = 0
    max_steps: int = 0
    compact: bool = True
    full_logs: list[str] = field(default_factory=list)

    def bind(self, app: Application, status: TextArea, logs: TextArea, answer: TextArea, reasoning: TextArea) -> None:
        self.app = app
        self.status = status
        self.logs = logs
        self.answer = answer
        self.reasoning = reasoning

    def on_step(self, step: int, max_steps: int) -> None:
        self.step = step
        self.max_steps = max_steps
        self._set_status("requesting")
        if self.answer:
            self.answer.text = ""
        if self.reasoning:
            self.reasoning.text = ""
        self._invalidate()

    def on_model_delta(self, content: str) -> None:
        if self.answer:
            self.answer.text += content
        self._set_status("streaming answer")
        self._invalidate()

    def on_model_message(self, content: str) -> None:
        if self.answer and not self.answer.text:
            self.answer.text = content
        self._set_status("answer received")
        self._invalidate()

    def on_reasoning_delta(self, content: str) -> None:
        if self.reasoning:
            self.reasoning.text += content
        self._set_status("streaming reasoning")
        self._invalidate()

    def on_reasoning(self, content: str) -> None:
        if self.reasoning and not self.reasoning.text:
            self.reasoning.text = content
        self._set_status("reasoning received")
        self._invalidate()

    def on_tool_start(self, name: str, arguments: dict[str, Any]) -> None:
        self._append_log(f"[tool] {name} {json.dumps(arguments, ensure_ascii=False)}")
        self._set_status(f"running {name}")
        self._invalidate()

    def on_tool_result(self, name: str, ok: bool, output: str) -> None:
        full = f"[{name} {'ok' if ok else 'error'}]\n{output}"
        self.full_logs.append(full)
        shown = summarize_tool_output(name, ok, output) if self.compact else _trim(output, 5000)
        self._append_log(f"[{name} {'ok' if ok else 'error'}]\n{shown}")
        self._set_status(f"{name} {'ok' if ok else 'failed'}")
        self._invalidate()

    def _set_status(self, text: str) -> None:
        if self.status:
            self.status.text = f"DeepSeek Codex CLI | {text} | step {self.step}/{self.max_steps} | F4 expand/compact"

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
    layout_mode: str = "balanced",
    compact: bool = True,
) -> int:
    events = SplitPaneAgentEvents(compact=compact)
    agent.events = events
    status = TextArea(text=f"DeepSeek Codex CLI | {cwd} | {model} | {session_name or 'no session'}", height=1, focusable=False)
    logs = TextArea(text="Compact output enabled. Use /expand or F4 for full logs.", scrollbar=True, focusable=True, wrap_lines=False)
    answer = TextArea(text="", scrollbar=True, focusable=True, wrap_lines=True)
    reasoning = TextArea(text="", scrollbar=True, focusable=True, wrap_lines=True)
    input_box = TextArea(height=3, prompt="DeepSeek> ", multiline=False)
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

    @bindings.add("f4")
    def _(event) -> None:
        events.compact = not events.compact
        logs.text = "\n\n".join(events.full_logs) if not events.compact else "Compact output enabled. Use /expand or F4 for full logs."
        event.app.invalidate()

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
        if prompt == "/expand":
            events.compact = False
            logs.text = "\n\n".join(events.full_logs) or logs.text
            return True
        if prompt == "/compact":
            events.compact = True
            logs.text = "Compact output enabled. Use /expand or F4 for full logs."
            return True
        result = agent.run_turn(prompt)
        answer.text = result or answer.text
        if on_turn_done:
            on_turn_done()
        return True

    input_box.buffer.accept_handler = submit
    body = build_split_layout(status, logs, reasoning, answer, input_box, layout_mode)
    app = Application(layout=Layout(body, focused_element=input_box), key_bindings=bindings, full_screen=True, mouse_support=True)
    events.bind(app, status, logs, answer, reasoning)
    return int(app.run() or 0)


def build_split_layout(status: TextArea, logs: TextArea, reasoning: TextArea, answer: TextArea, input_box: TextArea, layout_mode: str):
    if layout_mode == "logs-right":
        main = VSplit([HSplit([Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")]), Frame(logs, title="Logs")])
    elif layout_mode == "stacked":
        main = HSplit([Frame(logs, title="Logs"), Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")])
    else:
        main = VSplit([Frame(logs, title="Logs"), HSplit([Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")])])
    return HSplit([status, main, Frame(input_box, title="Input")])
