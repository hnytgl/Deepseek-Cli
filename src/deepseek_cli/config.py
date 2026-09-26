"""
deepseek_cli.config -- Configuration file support.

Loads settings from (in priority order, later overrides earlier):
  1. ~/.deepseek-cli/config.toml  (user-level defaults)
  2. .deepseek-cli/config.toml    (project-level overrides)
  3. Environment variables        (DEEPSEEK_API_KEY, DEEPSEEK_MODEL, etc.)
  4. CLI flags                    (highest priority)

Example config.toml:
    model = "deepseek-chat"
    approval = "auto-edit"
    theme = "dark"
    sandbox = "workspace"

    [reasoning]
    enabled = true
    model = "deepseek-reasoner"
    thinking_budget = 4096

    [shell]
    allow = ["git", "npm", "python", "pytest"]
    deny = ["rm -rf", "sudo"]
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ImportError:
    try:
        import tomli as tomllib  # type: ignore[no-redef]
    except ImportError:
        tomllib = None  # type: ignore[assignment]


_CONFIG_DIR_NAME = ".deepseek-cli"
_CONFIG_FILE_NAME = "config.toml"


def user_config_dir() -> Path:
    """Return the user-level config directory (~/.deepseek-cli/)."""
    return Path.home() / _CONFIG_DIR_NAME


def project_config_path(cwd: Path) -> Path:
    """Return the project-level config file path."""
    return cwd.resolve() / _CONFIG_DIR_NAME / _CONFIG_FILE_NAME


def user_config_path() -> Path:
    """Return the user-level config file path."""
    return user_config_dir() / _CONFIG_FILE_NAME


@dataclass
class ReasoningConfig:
    """DeepSeek reasoning mode configuration."""
    enabled: bool = False
    model: str = "deepseek-reasoner"
    thinking_budget: int = 4096  # max thinking tokens


@dataclass
class ShellConfig:
    """Shell command allow/deny lists."""
    allow: list[str] = field(default_factory=list)
    deny: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    """Application configuration loaded from config files."""
    # Core
    model: str = ""
    api_key: str = ""
    base_url: str = ""
    approval: str = ""  # suggest | auto-edit | full-auto
    sandbox: str = ""  # workspace | unrestricted
    theme: str = ""
    max_steps: int = 0
    temperature: float = 0.0
    stream: bool = True

    # Reasoning
    reasoning: ReasoningConfig = field(default_factory=ReasoningConfig)

    # Shell
    shell: ShellConfig = field(default_factory=ShellConfig)

    # UI
    quiet: bool = False
    layout: str = ""  # stacked | split
    expanded_output: bool = False

    # Project instructions
    agents_md: str = ""  # content of AGENTS.md if found


def _load_toml(path: Path) -> dict[str, Any]:
    """Load a TOML file, returning empty dict on any failure."""
    if not path.exists():
        return {}
    if tomllib is None:
        return {}
    try:
        with open(path, "rb") as f:
            return tomllib.load(f)
    except Exception:
        return {}


def load_config(cwd: Path | None = None) -> AppConfig:
    """
    Load configuration from all sources (files + env vars).

    Priority: env vars > project config > user config > defaults.
    CLI flags are applied on top of this in cli.py.
    """
    config = AppConfig()

    # 1. User-level config
    user_data = _load_toml(user_config_path())
    _apply_dict(config, user_data)

    # 2. Project-level config (overrides user)
    if cwd:
        project_data = _load_toml(project_config_path(cwd))
        _apply_dict(config, project_data)

    # 3. Environment variables (highest file priority)
    env_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if env_key:
        config.api_key = env_key
    env_model = os.environ.get("DEEPSEEK_MODEL", "")
    if env_model:
        config.model = env_model
    env_url = os.environ.get("DEEPSEEK_BASE_URL", "")
    if env_url:
        config.base_url = env_url
    env_theme = os.environ.get("DEEPSEEK_THEME", "")
    if env_theme:
        config.theme = env_theme

    # 4. Load AGENTS.md if present in project
    if cwd:
        config.agents_md = _load_agents_md(cwd)

    return config


def _apply_dict(config: AppConfig, data: dict[str, Any]) -> None:
    """Apply a TOML dict to the config dataclass."""
    if not data:
        return

    # Top-level scalar fields
    for key in ("model", "api_key", "base_url", "approval", "sandbox", "theme", "layout"):
        if key in data and isinstance(data[key], str):
            setattr(config, key, data[key])

    if "max_steps" in data and isinstance(data["max_steps"], int):
        config.max_steps = data["max_steps"]
    if "temperature" in data and isinstance(data["temperature"], (int, float)):
        config.temperature = float(data["temperature"])
    if "stream" in data and isinstance(data["stream"], bool):
        config.stream = data["stream"]
    if "quiet" in data and isinstance(data["quiet"], bool):
        config.quiet = data["quiet"]
    if "expanded_output" in data and isinstance(data["expanded_output"], bool):
        config.expanded_output = data["expanded_output"]

    # [reasoning] section
    reasoning = data.get("reasoning")
    if isinstance(reasoning, dict):
        if "enabled" in reasoning:
            config.reasoning.enabled = bool(reasoning["enabled"])
        if "model" in reasoning and isinstance(reasoning["model"], str):
            config.reasoning.model = reasoning["model"]
        if "thinking_budget" in reasoning and isinstance(reasoning["thinking_budget"], int):
            config.reasoning.thinking_budget = reasoning["thinking_budget"]

    # [shell] section
    shell = data.get("shell")
    if isinstance(shell, dict):
        if "allow" in shell and isinstance(shell["allow"], list):
            config.shell.allow = [str(c) for c in shell["allow"]]
        if "deny" in shell and isinstance(shell["deny"], list):
            config.shell.deny = [str(c) for c in shell["deny"]]


def _load_agents_md(cwd: Path) -> str:
    """
    Load project instructions from AGENTS.md (Codex-style).

    Searches for (in order):
      1. AGENTS.md
      2. .deepseek-cli/AGENTS.md
      3. DEEPSEEK.md

    Returns the content of the first file found, or empty string.
    """
    candidates = [
        cwd / "AGENTS.md",
        cwd / _CONFIG_DIR_NAME / "AGENTS.md",
        cwd / "DEEPSEEK.md",
    ]
    for path in candidates:
        if path.is_file():
            try:
                content = path.read_text(encoding="utf-8").strip()
                if content:
                    return content[:8192]  # cap at 8KB to avoid blowing context
            except (OSError, UnicodeDecodeError):
                continue
    return ""


def save_user_config(config: AppConfig) -> Path:
    """Save current config to user-level config.toml."""
    path = user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    lines = []
    if config.model:
        lines.append(f'model = "{config.model}"')
    if config.approval:
        lines.append(f'approval = "{config.approval}"')
    if config.sandbox:
        lines.append(f'sandbox = "{config.sandbox}"')
    if config.theme:
        lines.append(f'theme = "{config.theme}"')
    if config.max_steps:
        lines.append(f"max_steps = {config.max_steps}")
    if config.temperature:
        lines.append(f"temperature = {config.temperature}")
    if config.quiet:
        lines.append("quiet = true")

    if config.reasoning.enabled:
        lines.append("")
        lines.append("[reasoning]")
        lines.append("enabled = true")
        lines.append(f'model = "{config.reasoning.model}"')
        lines.append(f"thinking_budget = {config.reasoning.thinking_budget}")

    if config.shell.allow or config.shell.deny:
        lines.append("")
        lines.append("[shell]")
        if config.shell.allow:
            lines.append("allow = [{}]".format(", ".join(f'"{c}"' for c in config.shell.allow)))
        if config.shell.deny:
            lines.append("deny = [{}]".format(", ".join(f'"{c}"' for c in config.shell.deny)))

    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path
