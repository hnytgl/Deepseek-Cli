from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .agent import AgentConfig, DeepSeekAgent
from .api import DEFAULT_MODEL, DeepSeekAPIError, DeepSeekClient
from .tools import ToolExecutor


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
    parser.add_argument("--max-steps", type=int, default=24, help="Maximum model/tool loop steps.")
    parser.add_argument("--temperature", type=float, default=0.2, help="Sampling temperature.")
    parser.add_argument("--version", action="version", version="deepseek-codex-cli 0.1.0")
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
    tools = ToolExecutor(cwd, auto_approve=args.yes)
    return DeepSeekAgent(
        client=client,
        tools=tools,
        config=AgentConfig(cwd=cwd, max_steps=args.max_steps, temperature=args.temperature),
    )


def run_interactive(agent: DeepSeekAgent) -> int:
    print("DeepSeek CLI. Type /exit to quit, /clear to reset the conversation.")
    while True:
        try:
            prompt = input("\n深问> ").strip()
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
        if answer:
            print(f"\n{answer}")


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        agent = create_agent(args)
    except DeepSeekAPIError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    if args.prompt:
        answer = agent.run_turn(" ".join(args.prompt))
        if answer:
            print(f"\n{answer}")
        return 0
    return run_interactive(agent)


if __name__ == "__main__":
    raise SystemExit(main())
