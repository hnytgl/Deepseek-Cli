from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path

from . import __version__
from .agent import AgentConfig, DeepSeekAgent
from .api import DEFAULT_MODEL, DeepSeekAPIError, DeepSeekClient
from .config import AppConfig, ConfigError, load_config
from .policy import PermissionConfig, PermissionError as PolicyError, load_project_policy, save_project_policy, project_policy_path, normalize_approval, restrict_policy
from .session import SessionError, SessionStore
from .theme import THEMES
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


def positive_int(value: str) -> int:
    number = int(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def nonnegative_int(value: str) -> int:
    number = int(value)
    if number < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return number


def positive_float(value: str) -> float:
    number = float(value)
    if number <= 0:
        raise argparse.ArgumentTypeError("must be greater than zero")
    return number


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="deepseek",
        description="Codex-style DeepSeek CLI coding agent.",
    )
    parser.add_argument("prompt", nargs="*", help="Task to run. Omit for interactive mode.")
    parser.add_argument("--cwd", default=None, help="Workspace directory. Defaults to the directory where deepseek is launched.")
    parser.add_argument("--model", default=None, help=f"DeepSeek model. Defaults to env or {DEFAULT_MODEL}.")
    parser.add_argument("--base-url", default=None, help="DeepSeek API base URL.")
    parser.add_argument(
        "--provider", default=None,
        choices=["deepseek", "ollama", "lmstudio", "openai", "openrouter", "anthropic"],
        help="API provider. Local providers (ollama/lmstudio) don't need an API key.",
    )
    parser.add_argument("--profile", default=None, metavar="NAME",
                        help="Load a named profile from config.toml [profiles.NAME] section.")
    parser.add_argument("--api-key", default=None, help="DeepSeek API key. Prefer DEEPSEEK_API_KEY.")
    parser.add_argument("--api-timeout", type=positive_float, default=120, help="API request timeout in seconds.")
    parser.add_argument("--api-retries", type=nonnegative_int, default=3, help="Retries for HTTP 429, 5xx, and network errors.")
    parser.add_argument("--yes", "-y", action="store_true", help="Auto-approve all tool execution (alias for --approval full-auto).")
    parser.add_argument(
        "--approval",
        choices=["suggest", "auto-edit", "full-auto", "ask", "auto", "read-only"],
        default=None,
        help=(
            "Tool approval mode. Codex-style: suggest (read-only, ask before edits), "
            "auto-edit (auto-approve file edits, ask for shell), "
            "full-auto (auto-approve everything in sandbox). "
            "Legacy: ask/auto/read-only still supported."
        ),
    )
    parser.add_argument(
        "--sandbox",
        choices=["workspace", "unrestricted"],
        default=None,
        help="Restrict file tools to the workspace by default.",
    )
    parser.add_argument(
        "--sandbox-mode",
        choices=["auto", "none", "strict"],
        default="auto",
        help=(
            "OS-level sandbox for shell commands. auto=use best available "
            "(bwrap on Linux, seatbelt on macOS, restricted on Windows), "
            "none=disable OS sandbox, strict=fail if unavailable."
        ),
    )
    parser.add_argument("--no-shell", action="store_true", help="Disable shell and PR tools.")
    parser.add_argument("--allow-install-tools", action="store_true", help="Allow install_tool to install missing tools.")
    parser.add_argument("--allow-command", action="append", default=[], help="Allow only this shell command. Repeatable.")
    parser.add_argument("--deny-command", action="append", default=[], help="Block this shell command. Repeatable.")
    parser.add_argument("--save-policy", action="store_true", help="Save the effective permission policy into this project.")
    parser.add_argument("--show-policy", action="store_true", help="Print the effective permission policy and exit.")
    parser.add_argument("--session", default=None, help="Save and resume a named session.")
    parser.add_argument(
        "--save-sensitive",
        action="store_true",
        help="Save session messages without automatic secret and home-path redaction.",
    )
    parser.add_argument("--resume", action="store_true", help="Resume the latest or named session.")
    parser.add_argument(
        "--sessions",
        nargs="?",
        const="",
        metavar="QUERY",
        help="List saved sessions, optionally filtering by text, then exit.",
    )
    parser.add_argument("--replay-session", metavar="NAME", help="Print a saved session transcript and exit.")
    parser.add_argument("--no-stream", action="store_true", default=None, help="Disable streaming API responses.")
    parser.add_argument("--max-steps", type=positive_int, default=None, help="Maximum model/tool loop steps (default: 128).")
    parser.add_argument(
        "--max-context-chars",
        type=positive_int,
        default=None,
        help="Approximate maximum conversation context characters sent to the model.",
    )
    parser.add_argument("--temperature", type=float, default=None, help="Sampling temperature (default: 0.2).")
    parser.add_argument("-q", "--quiet", action="store_true", default=None, help="Quiet mode: minimal output, suitable for scripting.")
    parser.add_argument("--json", dest="json_output", action="store_true", help="Output result as JSON (for scripting/CI). Implies --quiet.")
    parser.add_argument("--plain", action="store_true", help="Use plain input/output instead of the Rich TUI.")
    parser.add_argument("--fullscreen", action="store_true", help="Use an alternate full-screen terminal surface.")
    parser.add_argument(
        "--reasoning", action="store_true",
        help="Enable reasoning mode using the configured reasoning model (default: deepseek-v4-pro).",
    )
    parser.add_argument(
        "--thinking-budget", type=positive_int, default=None,
        help="Max thinking tokens for reasoning mode (default: 4096).",
    )
    parser.add_argument(
        "--theme",
        choices=sorted(THEMES),
        default=None,
        help="TUI color theme. Can also be set with DEEPSEEK_THEME.",
    )
    parser.add_argument(
        "--layout",
        choices=["balanced", "logs-right", "stacked"],
        default=None,
        help="Fullscreen split-pane layout.",
    )
    parser.add_argument("--expanded-output", action="store_true", default=None, help="Show full tool output by default instead of compact summaries.")
    parser.add_argument("--doctor", action="store_true", help="Check local installation requirements.")
    parser.add_argument(
        "--completions", metavar="SHELL", choices=["bash", "zsh", "fish"],
        help="Print shell completion script and exit. Append to your shell rc file.",
    )
    parser.add_argument(
        "--self-update",
        nargs="?",
        const="git+https://github.com/hnytgl/deepseek-cli.git",
        metavar="SOURCE",
        help="Upgrade this CLI with pip. Defaults to the GitHub repository.",
    )
    parser.add_argument("--version", action="version", version=f"deepseek-codex-cli {__version__}")
    return parser


def resolve_settings(args: argparse.Namespace, cwd: Path) -> AppConfig:
    config = load_config(cwd, profile_name=args.profile)
    defaults = {
        "max_steps": config.max_steps,
        "max_context_chars": config.max_context_chars,
        "temperature": config.temperature,
        "no_stream": not config.stream,
        "thinking_budget": config.reasoning.thinking_budget,
        "quiet": config.quiet,
        "theme": config.theme or "default",
        "layout": config.layout or "balanced",
        "expanded_output": config.expanded_output,
    }
    for key, value in defaults.items():
        if getattr(args, key) is None:
            setattr(args, key, value)
    args.quiet = bool(args.quiet or args.json_output)
    for key in ("max_steps", "max_context_chars", "thinking_budget"):
        value = getattr(args, key)
        if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
            raise ConfigError(f"{key} must be a positive integer.")
    if args.theme not in THEMES:
        raise ConfigError(f"Invalid theme: {args.theme}")
    if args.layout not in {"balanced", "logs-right", "stacked"}:
        raise ConfigError(f"Invalid layout: {args.layout}")
    return config


def resolve_permissions(args: argparse.Namespace, cwd: Path, config: AppConfig) -> PermissionConfig:
    # CLI/user settings grant permissions; project files may only restrict them.
    raw_approval = args.approval or ("full-auto" if args.yes else None) or config.approval or "ask"
    sandbox = args.sandbox or config.sandbox or "workspace"
    if sandbox not in {"workspace", "unrestricted"}:
        raise PolicyError(f"Invalid sandbox: {sandbox}")
    policy = PermissionConfig(
        approval=normalize_approval(raw_approval),
        sandbox=sandbox, shell=not args.no_shell,
        allow_commands=tuple(c.lower() for c in args.allow_command) or tuple(config.shell.allow),
        deny_commands=tuple(c.lower() for c in args.deny_command) or tuple(config.shell.deny),
        install_tools=args.allow_install_tools,
    )
    for constraints in config.project_permissions:
        policy = restrict_policy(policy, constraints)
    if project_policy_path(cwd).exists():
        policy = restrict_policy(policy, load_project_policy(cwd).to_dict())
    return policy


def create_agent(args: argparse.Namespace) -> DeepSeekAgent:
    cwd = resolve_cwd(args.cwd)
    if not cwd.exists():
        raise SystemExit(f"Workspace does not exist: {cwd}")
    if not cwd.is_dir():
        raise SystemExit(f"Workspace is not a directory: {cwd}")

    file_config = resolve_settings(args, cwd)

    # Resolve model: CLI > env > config file > default
    model = args.model or file_config.model or None
    # Reasoning mode: switch to pro model (thinking mode)
    if not args.model and (args.reasoning or (file_config.reasoning.enabled and not os.getenv("DEEPSEEK_MODEL"))):
        model = file_config.reasoning.model or "deepseek-v4-pro"

    client = DeepSeekClient.from_env(
        api_key=args.api_key or file_config.api_key or None,
        base_url=args.base_url or file_config.base_url or None,
        model=model,
        timeout=args.api_timeout,
        max_retries=args.api_retries,
        provider=args.provider or file_config.provider or None,
    )

    policy = resolve_permissions(args, cwd, file_config)
    if args.save_policy:
        save_project_policy(cwd, policy)
    # auto-edit mode: auto-approve file edits, still ask for shell
    is_auto_edit = policy.approval == "auto-edit"

    # OS-level sandbox for shell commands
    from .sandbox import create_sandbox
    os_sandbox = create_sandbox(cwd, mode=args.sandbox_mode)

    tools = ToolExecutor(
        cwd,
        auto_approve=policy.auto_approve,
        auto_edit=is_auto_edit,
        ask=RichToolConfirmer(),
        approve_diff=RichDiffConfirmer(),
        approve_file_edits=RichFileEditConfirmer(),
        approve_hunks=RichHunkConfirmer(),
        policy=policy,
        sandbox=os_sandbox,
    )
    messages = []
    if args.resume or args.session:
        messages = SessionStore.default().load(args.session, latest=args.resume and not args.session)
        messages = [message for message in messages if message.get("role") != "system"]
    return DeepSeekAgent(
        client=client,
        tools=tools,
        config=AgentConfig(
            cwd=cwd,
            max_steps=args.max_steps,
            max_context_chars=args.max_context_chars,
            temperature=args.temperature,
            stream=not args.no_stream,
            thinking_budget=args.thinking_budget,
            quiet=args.quiet,
        ),
        messages=messages,
        agents_md=file_config.agents_md,
    )


def format_sessions(store: SessionStore, query: str = "") -> str:
    records = store.search(query)
    if not records:
        return "No saved sessions found."
    rows = []
    for record in records:
        updated = time.strftime("%Y-%m-%d %H:%M", time.localtime(record.updated_at))
        rows.append(f"{record.name}\t{updated}\t{len(record.messages)} messages\t{record.preview}")
    return "\n".join(rows)


def run_interactive(
    agent: DeepSeekAgent,
    *,
    session_name: str | None = None,
    save_sensitive: bool = False,
) -> int:
    print("DeepSeek CLI. Type /help for commands.")
    store = SessionStore.default()
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
        if prompt == "/help":
            print("/cost, /sessions [query], /replay NAME, /clear, /exit")
            continue
        if prompt == "/cost":
            print(agent.get_usage_summary())
            continue
        if prompt == "/sessions" or prompt.startswith("/sessions "):
            print(format_sessions(store, prompt.removeprefix("/sessions").strip()))
            continue
        if prompt.startswith("/replay "):
            name = prompt.removeprefix("/replay").strip()
            try:
                messages = store.load(name)
            except SessionError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                continue
            if not messages:
                print(f"Session not found: {name}", file=sys.stderr)
                continue
            agent.restore_messages(messages)
            print(f"Loaded session: {name}")
            continue
        if prompt == "/clear":
            agent.messages.clear()
            agent.__post_init__()
            print("Conversation cleared.")
            continue

        try:
            answer = agent.run_turn(prompt)
        except DeepSeekAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            continue
        save_session(agent, session_name, save_sensitive=save_sensitive)
        if answer:
            print(f"\n{answer}")


def save_session(agent: DeepSeekAgent, session_name: str | None, *, save_sensitive: bool = False) -> None:
    if not session_name:
        return
    SessionStore.default().save(
        session_name,
        agent.messages,
        cwd=agent.config.cwd,
        model=agent.client.model,
        redact=not save_sensitive,
    )


def resolve_cwd(value: str | None) -> Path:
    if not value:
        return Path.cwd().resolve()
    return Path(value).expanduser().resolve()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.completions:
        from .completions import get_completion_script
        print(get_completion_script(args.completions))
        return 0
    if args.doctor:
        report = run_doctor()
        print(report.output)
        return 0 if report.ok else 1
    if args.self_update:
        return self_update(args.self_update)
    store = SessionStore.default()
    try:
        if args.sessions is not None:
            print(format_sessions(store, args.sessions))
            return 0
        if args.replay_session:
            print(store.transcript(args.replay_session))
            return 0
    except SessionError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2
    if args.show_policy:
        cwd = resolve_cwd(args.cwd)
        try:
            config = resolve_settings(args, cwd)
            policy = resolve_permissions(args, cwd, config)
        except (PolicyError, ConfigError) as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        import json

        print(json.dumps(policy.to_dict(), ensure_ascii=False, indent=2))
        return 0
    try:
        agent = create_agent(args)
    except (DeepSeekAPIError, PolicyError, SessionError, ConfigError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.prompt:
        if args.quiet:
            # Quiet mode: no events, just the final answer to stdout
            pass
        elif not args.plain:
            from rich.console import Console

            console = Console()
            agent.events = RichAgentEvents(console, theme_name=args.theme)
        try:
            answer = agent.run_turn(" ".join(args.prompt))
        except DeepSeekAPIError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 2
        save_session(agent, args.session, save_sensitive=args.save_sensitive)
        if args.json_output:
            import json as _json
            result = {
                "answer": answer or "",
                "model": agent.client.model,
                "usage": {
                    "prompt_tokens": agent.total_prompt_tokens,
                    "completion_tokens": agent.total_completion_tokens,
                    "total_requests": agent.total_requests,
                },
                "modified_files": [str(f) for f in agent.tools.modified_files],
            }
            print(_json.dumps(result, ensure_ascii=False))
        elif answer:
            print(f"\n{answer}" if not args.quiet else answer)
        return 0
    if args.quiet or args.plain:
        return run_interactive(agent, session_name=args.session, save_sensitive=args.save_sensitive)
    if args.fullscreen:
        code = run_split_pane_interactive(
            agent,
            cwd=agent.config.cwd,
            model=agent.client.model,
            session_name=args.session,
            on_turn_done=lambda: save_session(agent, args.session, save_sensitive=args.save_sensitive),
            layout_mode=args.layout,
            compact=not args.expanded_output,
            theme_name=args.theme,
        )
        save_session(agent, args.session, save_sensitive=args.save_sensitive)
        return code
    code = run_rich_interactive(
        agent,
        cwd=agent.config.cwd,
        model=agent.client.model,
        session_name=args.session,
        on_turn_done=lambda: save_session(agent, args.session, save_sensitive=args.save_sensitive),
        compact=not args.expanded_output,
        theme_name=args.theme,
    )
    save_session(agent, args.session, save_sensitive=args.save_sensitive)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
