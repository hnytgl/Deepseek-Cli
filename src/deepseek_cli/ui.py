from __future__ import annotations

import json
import subprocess
import threading
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
from .session import SessionError, SessionStore, default_session_dir
from .theme import Theme, get_theme


def _trim(text: str, limit: int = 5000) -> str:
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n... truncated, original length {len(text)} chars"


def summarize_tool_output(name: str, ok: bool, output: str) -> str:
    formatted = format_tool_output(name, output, compact=True)
    return f"{formatted}\n\n{len(output)} chars captured. Use /logs, /expand, or F4 to open full output."


def format_tool_output(name: str, output: str, *, compact: bool) -> str:
    limit = 1200 if compact else 8000
    if name == "read_file":
        try:
            payload = json.loads(output)
        except json.JSONDecodeError:
            return _trim(output, limit)
        content = str(payload.get("content") or "")
        header = (
            f"file: {payload.get('path')}\n"
            f"range: {payload.get('offset')}..{payload.get('end_offset')} / {payload.get('total_chars')}"
        )
        if payload.get("has_more"):
            header += f"\nnext: read_file offset={payload.get('next_offset')} limit={payload.get('limit')}"
        return f"{header}\n\n--- content ---\n{_trim(content, limit)}"
    if name in {"git_diff", "git_status"}:
        return _trim(output, 3000 if compact else limit)
    if name == "shell":
        return _trim(output, limit)
    return _trim(output, limit)


@dataclass
class RichAgentEvents(AgentEventHandler):
    console: Console
    max_log_items: int = 12
    compact: bool = True
    theme_name: str = "default"
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
        theme = get_theme(self.theme_name)
        self.console.clear()
        self.console.print(render_header(self.step, self.max_steps, self.current_status, theme))
        if self.streaming_reasoning:
            self.console.print(Panel(_trim(self.streaming_reasoning, 300 if self.compact else 1600), title="reasoning", border_style=theme.reasoning))
        if self.streaming_answer:
            self.console.print(Panel(Markdown(_trim(self.streaming_answer, 700 if self.compact else 2200)), title="answer draft", border_style=theme.success))
        for title, body in self.logs:
            style = theme.accent if title.startswith("tool") else theme.reasoning if title == "reasoning" else theme.success
            rendered = summarize_tool_output(title, True, body) if self.compact and title == "tool result" else _trim(body, 500 if self.compact else 5000)
            self.console.print(Panel(rendered, title=title, border_style=style))


def render_header(step: int, max_steps: int, status: str, theme: Theme | None = None) -> Panel:
    theme = theme or get_theme("default")
    table = Table.grid(expand=True)
    table.add_column(ratio=2)
    table.add_column(ratio=3)
    step_text = f"{step}/{max_steps}" if max_steps else "0/0"
    progress = Progress(TextColumn("[bold]progress[/bold]"), BarColumn(bar_width=None), TextColumn(step_text), expand=True)
    task = progress.add_task("agent", total=max_steps or 1, completed=step)
    progress.update(task, completed=step)
    table.add_row(Text("DeepSeek Codex CLI", style=f"bold {theme.accent}"), Text(status, style="bold"))
    table.add_row("", progress)
    return Panel(table, border_style=theme.accent)


def print_welcome(console: Console, cwd: Path, model: str, session_name: str | None, theme: Theme) -> None:
    body = Table.grid(padding=(0, 1))
    body.add_column(style="bold")
    body.add_column()
    body.add_row("workspace", str(cwd))
    body.add_row("model", model)
    body.add_row("session", session_name or "none")
    body.add_row("theme", theme.name)
    body.add_row("commands", "/sessions, /replay, /review, /logs, /clear, /help, /exit")
    console.print(Panel(body, title="DeepSeek CLI", border_style=theme.accent))


def print_help(console: Console, theme: Theme) -> None:
    console.print(
        Panel(
            "/exit or /quit: exit\n"
            "/clear: clear conversation\n"
            "/sessions [query]: list or search saved sessions\n"
            "/replay NAME: load a saved session into this conversation\n"
            "/logs: open full logs in a pager\n"
            "/review: show current git diff\n"
            "/status: show current task progress\n"
            "/cancel: stop after the current model/tool step when possible\n"
            "/compact: compact Codex-like output\n"
            "/expand: full output mode\n"
            "/help: show help\n\n"
            "Fullscreen keys: F4 toggles compact/full logs, Tab changes focus, Ctrl+L clears panes, Ctrl+D exits.",
            title="help",
            border_style=theme.accent,
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
    theme = get_theme(events.theme_name)
    with console.pager(styles=True):
        console.print(render_header(events.step, events.max_steps, events.current_status, theme))
        if events.streaming_reasoning:
            console.print(Panel(events.streaming_reasoning, title="reasoning", border_style=theme.reasoning))
        if events.streaming_answer:
            console.print(Panel(Markdown(events.streaming_answer), title="answer", border_style=theme.success))
        for title, body in events.logs:
            console.print(Panel(body, title=title))


def show_git_review(console: Console, cwd: Path) -> None:
    completed = subprocess.run(
        ["git", "diff", "--", "."],
        cwd=cwd,
        text=True,
        errors="replace",
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
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
    theme_name: str = "default",
) -> int:
    console = Console()
    events = RichAgentEvents(console, compact=compact, theme_name=theme_name)
    agent.events = events
    return _run_loop(console, events, agent, cwd, model, session_name, on_turn_done, get_theme(theme_name))


def _run_loop(
    console: Console,
    events: RichAgentEvents,
    agent: DeepSeekAgent,
    cwd: Path,
    model: str,
    session_name: str | None,
    on_turn_done: Callable[[], None] | None,
    theme: Theme,
) -> int:
    print_welcome(console, cwd, model, session_name, theme)
    prompt_session = make_prompt_session()
    store = SessionStore.default()

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
            print_help(console, theme)
            continue
        if prompt == "/sessions" or prompt.startswith("/sessions "):
            query = prompt.removeprefix("/sessions").strip()
            records = store.search(query)
            table = Table(title="Saved sessions")
            table.add_column("name")
            table.add_column("updated")
            table.add_column("preview")
            for record in records:
                table.add_row(record.name, str(record.updated_at), record.preview)
            console.print(table if records else "No saved sessions found.")
            continue
        if prompt.startswith("/replay "):
            name = prompt.removeprefix("/replay").strip()
            try:
                messages = store.load(name)
            except SessionError as exc:
                console.print(f"[{theme.error}]Error: {exc}[/{theme.error}]")
                continue
            if not messages:
                console.print(f"[{theme.warning}]Session not found: {name}[/{theme.warning}]")
                continue
            agent.messages = messages
            console.print(f"Loaded session: {name}")
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
        console.print(Panel(Markdown(answer or "Done."), title="final", border_style=theme.success))


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
    console = Console()
    old_lines = hunk.old_text.splitlines()
    new_lines = hunk.new_text.splitlines()
    table = Table(title=f"Line edit: {hunk.path}", show_lines=True)
    table.add_column("#", style="bold")
    table.add_column("old", style="red")
    table.add_column("new", style="green")
    width = max(len(old_lines), len(new_lines))
    for index in range(width):
        old = old_lines[index] if index < len(old_lines) else ""
        new = new_lines[index] if index < len(new_lines) else ""
        table.add_row(str(index + 1), old, new)
    console.print(table)
    choice = Prompt.ask(
        "Keep which new lines? Use all, none, comma numbers, or text",
        default="all",
        console=console,
    ).strip()
    if choice == "all":
        return hunk.new_text
    if choice == "none":
        return hunk.old_text
    if choice == "text":
        console.print("Enter replacement lines. Submit a single '.' line to finish.")
        lines: list[str] = []
        while True:
            line = Prompt.ask("", console=console)
            if line == ".":
                break
            lines.append(line)
        return "\n".join(lines) + ("\n" if hunk.new_text.endswith("\n") else "")
    selected: list[str] = []
    try:
        numbers = {int(part.strip()) for part in choice.split(",") if part.strip()}
    except ValueError:
        console.print("[red]Invalid line list; keeping old hunk.[/red]")
        return hunk.old_text
    for index, line in enumerate(new_lines, start=1):
        if index in numbers:
            selected.append(line)
    suffix = "\n" if hunk.new_text.endswith("\n") and selected else ""
    return "\n".join(selected) + suffix


@dataclass
class SplitPaneAgentEvents(AgentEventHandler):
    app: Application | None = None
    status: TextArea | None = None
    logs: TextArea | None = None
    answer: TextArea | None = None
    reasoning: TextArea | None = None
    activity: TextArea | None = None
    step: int = 0
    max_steps: int = 0
    compact: bool = True
    full_logs: list[str] = field(default_factory=list)

    def bind(self, app: Application, status: TextArea, logs: TextArea, answer: TextArea, reasoning: TextArea, activity: TextArea) -> None:
        self.app = app
        self.status = status
        self.logs = logs
        self.answer = answer
        self.reasoning = reasoning
        self.activity = activity

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
        self._append_activity(f"tool: {name}")
        self._append_log(f"== tool: {name} ==\n{json.dumps(arguments, ensure_ascii=False, indent=2)}")
        self._set_status(f"running {name}")
        self._invalidate()

    def on_tool_result(self, name: str, ok: bool, output: str) -> None:
        full = f"[{name} {'ok' if ok else 'error'}]\n{output}"
        self.full_logs.append(full)
        shown = summarize_tool_output(name, ok, output) if self.compact else format_tool_output(name, output, compact=False)
        self._append_log(f"== {name} {'ok' if ok else 'error'} ==\n{shown}")
        self._set_status(f"{name} {'ok' if ok else 'failed'}")
        self._invalidate()

    def _set_status(self, text: str) -> None:
        if self.status:
            self.status.text = f"DeepSeek Codex CLI | {text} | step {self.step}/{self.max_steps} | F4 expand/compact"

    def _append_log(self, text: str) -> None:
        if self.logs:
            self.logs.text = (self.logs.text + "\n\n" + text).strip()

    def _append_activity(self, text: str) -> None:
        if self.activity:
            self.activity.text = (self.activity.text + "\n" + text).strip()

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
    theme_name: str = "default",
) -> int:
    theme = get_theme(theme_name)
    events = SplitPaneAgentEvents(compact=compact)
    agent.events = events
    status = TextArea(text=f"DeepSeek Codex CLI | {cwd} | {model} | {session_name or 'no session'}", height=1, focusable=False)
    logs = TextArea(text="Compact output enabled. Use /expand or F4 for full logs.", scrollbar=True, focusable=True, wrap_lines=False)
    answer = TextArea(text="", scrollbar=True, focusable=True, wrap_lines=True)
    reasoning = TextArea(text="", scrollbar=True, focusable=True, wrap_lines=True)
    activity = TextArea(text="Ready. Type a task, /sessions, /replay, /review, or /help.", scrollbar=True, focusable=True, wrap_lines=True)
    input_box = TextArea(height=3, prompt="DeepSeek> ", multiline=False)
    bindings = KeyBindings()
    state: dict[str, Any] = {"running": False, "cancel_requested": False, "last_prompt": "", "approval": None}
    lock = threading.Lock()
    agent.config.cancel_check = lambda: bool(state["cancel_requested"])
    store = SessionStore.default()

    def request_decision(prompt: str, detail: str = "") -> bool:
        event = threading.Event()
        request = {"prompt": prompt, "detail": detail, "event": event, "result": False}
        state["approval"] = request
        events._append_activity(f"approval needed: {prompt}\nType y/yes//approve or n/no//reject.")
        if detail:
            logs.text = detail
        events._set_status("waiting for approval")
        events._invalidate()
        event.wait()
        state["approval"] = None
        return bool(request["result"])

    def request_hunk_decisions(hunks: list[PatchHunk]) -> list[HunkDecision]:
        decisions: list[HunkDecision] = []
        for index, hunk in enumerate(hunks, start=1):
            detail = f"Hunk {index}/{len(hunks)}: {hunk.path}\n\n{hunk.diff}"
            accepted = request_decision("Accept this hunk?", detail)
            decisions.append(accepted)
        return decisions

    agent.tools.ask = request_decision
    agent.tools.approve_diff = lambda prompt, diff: request_decision(prompt, diff)
    agent.tools.approve_hunks = request_hunk_decisions

    @bindings.add("c-d")
    def _(event) -> None:
        if state["running"]:
            state["cancel_requested"] = True
            events._append_activity("Cancel requested. Exit after current step returns.")
            event.app.invalidate()
        else:
            event.app.exit(result=0)

    @bindings.add("c-l")
    def _(event) -> None:
        logs.text = ""
        answer.text = ""
        reasoning.text = ""
        activity.text = ""
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
        if resolve_pending_approval(prompt):
            return True
        if handle_split_command(prompt):
            return True

        with lock:
            if state["running"]:
                events._append_activity("Task is still running. Use /status, /cancel, /review, /expand, or /compact.")
                events._invalidate()
                return True
            state["running"] = True
            state["cancel_requested"] = False
            state["last_prompt"] = prompt

        answer.text = ""
        reasoning.text = ""
        events._append_activity(f"user: {prompt}")
        events._set_status("running in background")

        def worker() -> None:
            try:
                result = agent.run_turn(prompt)
                if result:
                    answer.text = result
            except Exception as exc:
                events._append_log(f"[error]\n{exc}")
                events._set_status("error")
            finally:
                with lock:
                    state["running"] = False
                    state["cancel_requested"] = False
                if on_turn_done:
                    on_turn_done()
                events._set_status("ready")
                events._invalidate()

        threading.Thread(target=worker, daemon=True).start()
        events._invalidate()
        return True

    def resolve_pending_approval(prompt: str) -> bool:
        request = state.get("approval")
        if not request:
            return False
        normalized = prompt.strip().lower()
        if normalized in {"y", "yes", "/approve", "approve"}:
            request["result"] = True
        elif normalized in {"n", "no", "/reject", "reject"}:
            request["result"] = False
        elif normalized == "/cancel":
            state["cancel_requested"] = True
            request["result"] = False
            events._append_activity("Approval rejected and cancel requested.")
        elif normalized == "/expand":
            events.compact = False
            logs.text = "\n\n".join(events.full_logs) or logs.text
            events._append_activity("expanded logs; approval still pending")
            events._invalidate()
            return True
        elif normalized == "/compact":
            events.compact = True
            logs.text = request.get("detail") or "Compact output enabled. Use /expand or F4 for full logs."
            events._append_activity("compact logs; approval still pending")
            events._invalidate()
            return True
        elif normalized == "/review":
            completed = subprocess.run(
                ["git", "diff", "--", "."],
                cwd=cwd,
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            logs.text = completed.stdout or completed.stderr or "No git diff."
            events._append_activity("review opened; approval still pending")
            events._invalidate()
            return True
        elif normalized in {"/status", "status"}:
            events._append_activity(f"waiting approval: {request['prompt']}")
            events._invalidate()
            return True
        else:
            events._append_activity("Approval pending. Type y/yes//approve or n/no//reject.")
            events._invalidate()
            return True
        request["event"].set()
        events._append_activity("approved" if request["result"] else "rejected")
        events._invalidate()
        return True

    def handle_split_command(prompt: str) -> bool:
        if prompt == "/help":
            events._append_activity("commands: /sessions [query], /replay NAME, /status, /cancel, /review, /expand, /compact, /clear, /exit.")
            events._invalidate()
            return True
        if prompt == "/sessions" or prompt.startswith("/sessions "):
            query = prompt.removeprefix("/sessions").strip()
            records = store.search(query)
            logs.text = "\n".join(
                f"{record.name} | {record.model or '?'} | {record.preview}" for record in records
            ) or "No saved sessions found."
            events._append_activity(f"session search: {query or '(all)'}")
            events._invalidate()
            return True
        if prompt.startswith("/replay "):
            if state["running"]:
                events._append_activity("Cannot replay while a task is running. Use /cancel first.")
                events._invalidate()
                return True
            name = prompt.removeprefix("/replay").strip()
            try:
                messages = store.load(name)
            except SessionError as exc:
                events._append_activity(f"session error: {exc}")
                events._invalidate()
                return True
            if not messages:
                events._append_activity(f"Session not found: {name}")
                events._invalidate()
                return True
            agent.messages = messages
            activity.text = f"Loaded session: {name}"
            events._invalidate()
            return True
        if prompt in {"/exit", "/quit"}:
            if state["running"]:
                state["cancel_requested"] = True
                events._append_activity("Cancel requested. Exit will happen after the current step returns.")
                events._invalidate()
                return True
            app.exit(result=0)
            return True
        if prompt == "/clear":
            if state["running"]:
                events._append_activity("Cannot clear while a task is running. Use /cancel first.")
                events._invalidate()
                return True
            agent.messages.clear()
            agent.__post_init__()
            logs.text = ""
            answer.text = ""
            reasoning.text = ""
            activity.text = "Conversation cleared."
            return True
        if prompt == "/review":
            completed = subprocess.run(
                ["git", "diff", "--", "."],
                cwd=cwd,
                text=True,
                errors="replace",
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                timeout=60,
            )
            logs.text = completed.stdout or completed.stderr or "No git diff."
            events._append_activity("review opened in Logs panel")
            return True
        if prompt == "/status":
            running = "running" if state["running"] else "idle"
            approval = "; waiting approval" if state.get("approval") else ""
            events._append_activity(f"status: {running}; step {events.step}/{events.max_steps}; prompt: {state['last_prompt'] or '(none)'}{approval}")
            events._invalidate()
            return True
        if prompt == "/cancel":
            if state["running"]:
                state["cancel_requested"] = True
                events._append_activity("Cancel requested. Current model request or shell command may need to return first.")
                events._set_status("cancel requested")
            else:
                events._append_activity("No task is running.")
            events._invalidate()
            return True
        if prompt == "/expand":
            events.compact = False
            logs.text = "\n\n".join(events.full_logs) or logs.text
            events._append_activity("expanded logs")
            return True
        if prompt == "/compact":
            events.compact = True
            logs.text = "Compact output enabled. Use /expand or F4 for full logs."
            events._append_activity("compact logs")
            return True
        return False

    input_box.buffer.accept_handler = submit
    body = build_split_layout(status, logs, reasoning, answer, activity, input_box, layout_mode)
    app = Application(
        layout=Layout(body, focused_element=input_box),
        key_bindings=bindings,
        full_screen=True,
        mouse_support=True,
        style=theme.prompt_style,
    )
    events.bind(app, status, logs, answer, reasoning, activity)
    return int(app.run() or 0)


def build_split_layout(status: TextArea, logs: TextArea, reasoning: TextArea, answer: TextArea, activity: TextArea, input_box: TextArea, layout_mode: str):
    if layout_mode == "logs-right":
        execution = VSplit([HSplit([Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")]), Frame(logs, title="Logs")])
    elif layout_mode == "stacked":
        execution = HSplit([Frame(logs, title="Logs"), Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")])
    else:
        execution = VSplit([Frame(logs, title="Logs"), HSplit([Frame(reasoning, title="Reasoning"), Frame(answer, title="Answer")])])
    interaction = HSplit([Frame(activity, title="Interaction"), Frame(input_box, title="Input")], height=8)
    return HSplit([status, Frame(execution, title="Execution"), interaction])
