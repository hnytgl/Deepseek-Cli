from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .agent import AgentConfig, DeepSeekAgent
from .api import DEFAULT_MODEL, DeepSeekAPIError, DeepSeekClient
from .policy import PermissionConfig, load_project_policy, save_project_policy
from .session import SessionStore
from .tools import ToolExecutor
from .ui import (
    RichAgentEvents,
    RichDiffConfirmer,
    RichFileEditConfirmer,
    RichHunkConfirmer,
    RichToolConfirmer,
    run_rich_interactive,
    run_split_pane_interactive,
)
from .updater import run_doctor, self_update


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepseek",
        description="Codex-style DeepSeek CLI coding agent.",
    )
    parser.add_argument("prompt", nargs="*", help="Task to run. Omit for interactive mode.")
    parser.add_argument("--cwd", default=".", help="Workspace directory. Defaults to current directory.")
    parser.add_argument("--model", default=None, help=f"DeepSeek model. Defaults to env or {DEFAULT_MODEL}.")
    parser.add_argument("--base-url", default=None, help="DeepSeek API base URL.")
    parser.add_argument("--api-key", default=None, help="DeepSeek API key. Prefer DEEPSEEK_API_KEY.")
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-approve tool execution.")
    parser.add_argument(
        "--approval",
        choices=["ask", "auto", "read-only"],
        default=None,
        help="Tool approval mode. --yes is an alias for --approval auto.",
    )
    parser.add_argument(
        "--sandbox",
        choices=["workspace", "unrestricted"],
        default=None,
        help="Restrict file tools to the workspace by default.",
    )
    parser.add_argument("--no-shell", action="store_true", help="Disable shell and PR tools.")
    parser.add_argument("--allow-install-tools", action="store_true", help="Allow install_tool to install missing tools.")
    parser.add_argument("--allow-command", action="append", default=[], help="Allow only this shell command. Repeatable.")
    parser.add_argument("--deny-command", action="append", default=[], help="Block this shell command. Repeatable.")
    parser.add_argument("--save-policy", action="store_true", help="Save the effective permission policy into this project.")
    parser.add_argument("--show-policy", action="store_true", help="Print the effective permission policy and exit.")
    parser.add_argument("--session", default=None, help="Save and resume a named session.")
    parser.add_argument("--resume", action="store_true", help="Resume the latest or named session.")
    parser.add_argument("--no-stream", action="store_true", help="Disable streaming API responses.")
    parser.add_argument("--max-steps", type=int, default=24, help="Maximum model/tool loop steps.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature.")
    parser.add_argument("--plain", action="store_true", help="Use plain input/output instead of the Rich TUI.")
    parser.add_argument("--fullscreen", action="store_true", help="Use an alternate full-screen terminal surface.")
    parser.add_argument(
        "--layout",
        choices=["balanced", "logs-right", "stacked"],
        default="balanced",
        help="Fullscreen split-pane layout.",
    )
    parser.add_argument("--expanded-output", action="store_true", help="Show full tool output by default instead of compact summaries.")
    parser.add_argument("--doctor", action="store_true", help="Check local installation requirements.")
    parser.add_argument(
        "--self-update",
        nargs="?",
        const="git+https://github.com/hnytgl/deepseek-cli.git",
        metavar="SOURCE",
        help="Upgrade this CLI with pip. Defaults to the GitHub repository.",
    )
    parser.add_argument("--version", action="version", version=f"deepseek-codex-cli {__version__}")
    return parser


def create_agent(args: argparse.Namespace) -> DeepSeekAgent:
    cwd = Path(args.cwd).expanduser().resolve()
    if not cwd.exists():
        raise SystemExit(f"Workspace does not exist: {cwd}")
    if not cwd.is_dir():
        raise SystemExit(f"Workspace is not a directory: {cwd}")

    client = DeepSeekClient.from_env(
        api_key=args.api_key,
        base_url=args.base_url,
        model=args.model,
    )
    base_policy = load_project_policy(cwd)
    approval = "auto" if args.yes else (args.approval or base_policy.approval)
    policy = PermissionConfig(
        approval=approval,
        sandbox=args.sandbox or base_policy.sandbox,
        shell=base_policy.shell and not args.no_shell,
        allow_commands=tuple(command.lower() for command in args.allow_command) or base_policy.allow_commands,
        deny_commands=tuple(command.lower() for command in args.deny_command) or base_policy.deny_commands,
        install_tools=base_policy.install_tools or args.allow_install_tools,
    )
    if args.save_policy:
        save_project_policy(cwd, policy)
    tools = ToolExecutor(
        cwd,
        auto_approve=args.yes,
        ask=RichToolConfirmer(),
        approve_diff=RichDiffConfirmer(),
        approve_file_edits=RichFileEditConfirmer(),
        approve_hunks=RichHunkConfirmer(),
        policy=policy,
    )
    messages = []
    if args.resume or args.session:
        messages = SessionStore.default().load(args.session, latest=args.resume and not args.session)
    return DeepSeekAgent(
        client=client,
        tools=tools,
        config=AgentConfig(cwd=cwd, max_steps=args.max_steps, temperature=args.temperature, stream=not args.no_stream),
        messages=messages,
    )


def run_interactive(agent: DeepSeekAgent, *, session_name: str | None = None) -> int:
    print("DeepSeek CLI. Type /exit to quit, /clear to reset the conversation.")
    while True:
        try:
            prompt = input("\nDeepSeek> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0

        if not prompt:
            continue
        if prompt in {"/exit", "/quit"}:
            return 0
        if prompt == "/clear":
            agent.messages.clear()
            agent.__post_init__()
            print("Conversation cleared.")
            continue

        answer = agent.run_turn(prompt)
        save_session(agent, session_name)
        if answer:
            print(f"\n{answer}")


def save_session(agent: DeepSeekAgent, session_name: str | None) -> None:
    if not session_name:
        return
    SessionStore.default().save(session_name, agent.messages, cwd=agent.config.cwd, model=agent.client.model)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.doctor:
        report = run_doctor()
        print(report.output)
        return 0 if report.ok else 1
    if args.self_update:
        return self_update(args.self_update)
    if args.show_policy:
        cwd = Path(args.cwd).expanduser().resolve()
        base_policy = load_project_policy(cwd)
        policy = PermissionConfig(
            approval="auto" if args.yes else (args.approval or base_policy.approval),
            sandbox=args.sandbox or base_policy.sandbox,
            shell=base_policy.shell and not args.no_shell,
            allow_commands=tuple(command.lower() for command in args.allow_command) or base_policy.allow_commands,
            deny_commands=tuple(command.lower() for command in args.deny_command) or base_policy.deny_commands,
            install_tools=base_policy.install_tools or args.allow_install_tools,
        )
        import json

        print(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2))
        return 0
    try:
        agent = create_agent(args)
    except DeepSeekAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.prompt:
        if not args.plain:
            from rich.console import Console

            console = Console()
            agent.events = RichAgentEvents(console)
        answer = agent.run_turn(" ".join(args.prompt))
        save_session(agent, args.session)
        if answer:
            print(f"\n{answer}")
        return 0
    if args.plain:
        return run_interactive(agent, session_name=args.session)
    if args.fullscreen:
        code = run_split_pane_interactive(
            agent,
            cwd=Path(args.cwd).expanduser().resolve(),
            model=agent.client.model,
            session_name=args.session,
            on_turn_done=lambda: save_session(agent, args.session),
            layout_mode=args.layout,
            compact=not args.expanded_output,
        )
        save_session(agent, args.session)
        return code
    code = run_rich_interactive(
        agent,
        cwd=Path(args.cwd).expanduser().resolve(),
        model=agent.client.model,
        session_name=args.session,
        on_turn_done=lambda: save_session(agent, args.session),
        compact=not args.expanded_output,
    )
    save_session(agent, args.session)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
