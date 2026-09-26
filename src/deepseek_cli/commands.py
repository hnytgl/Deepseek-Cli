"""
deepseek_cli.commands -- Shared slash-command registry for all UI frontends.

Eliminates the inconsistency between plain/rich/fullscreen modes where
commands were duplicated (and sometimes missing) across three separate
if/elif chains. Each frontend still renders differently, but the command
table and help text are shared.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class Command:
    """Metadata for a single slash command."""
    name: str
    help: str
    args: str = ""          # e.g. "[query]" or "NAME"
    needs_agent: bool = False   # requires active agent (not available pre-connect)
    fullscreen_only: bool = False  # only meaningful in fullscreen mode


# Single source of truth for all interactive commands.
# Both rich mode and fullscreen mode reference this table.
COMMANDS: list[Command] = [
    Command("/help", "显示帮助"),
    Command("/cost", "显示 token 用量和估算费用"),
    Command("/undo", "撤销上一次文件修改（恢复到编辑前 checkpoint）"),
    Command("/clear", "清空当前对话上下文"),
    Command("/sessions", "列出或搜索已保存会话", args="[query]"),
    Command("/replay", "加载指定会话到当前对话", args="NAME"),
    Command("/review", "显示当前 Git diff"),
    Command("/logs", "打开可滚动日志视图"),
    Command("/status", "查看当前任务进度", fullscreen_only=True),
    Command("/cancel", "请求取消当前任务", fullscreen_only=True),
    Command("/compact", "切换到紧凑输出模式"),
    Command("/expand", "展开完整工具输出"),
    Command("/exit", "退出（也可用 /quit）"),
]


def format_help(include_fullscreen: bool = False) -> str:
    """Generate help text from the command registry."""
    lines = []
    for cmd in COMMANDS:
        if cmd.fullscreen_only and not include_fullscreen:
            continue
        usage = f"{cmd.name} {cmd.args}".strip() if cmd.args else cmd.name
        lines.append(f"  {usage:<24} {cmd.help}")
    return "\n".join(lines)


def command_names() -> list[str]:
    """Return all command names (for tab-completion)."""
    return [cmd.name for cmd in COMMANDS] + ["/quit"]


def is_command(text: str) -> bool:
    """Check if input text is a slash command."""
    if not text.startswith("/"):
        return False
    name = text.split()[0] if text else ""
    return name in {cmd.name for cmd in COMMANDS} or name == "/quit"
