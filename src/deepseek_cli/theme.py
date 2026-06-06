from __future__ import annotations

from dataclasses import dataclass

from prompt_toolkit.styles import Style


@dataclass(frozen=True)
class Theme:
    name: str
    accent: str
    success: str
    warning: str
    error: str
    reasoning: str
    prompt_style: Style


THEMES = {
    "default": Theme(
        name="default",
        accent="cyan",
        success="green",
        warning="yellow",
        error="red",
        reasoning="magenta",
        prompt_style=Style.from_dict(
            {
                "frame.label": "bold cyan",
                "text-area": "",
                "status": "reverse",
            }
        ),
    ),
    "ocean": Theme(
        name="ocean",
        accent="bright_blue",
        success="bright_cyan",
        warning="bright_yellow",
        error="bright_red",
        reasoning="blue_violet",
        prompt_style=Style.from_dict(
            {
                "frame.label": "bold #5fd7ff",
                "text-area": "bg:#071b2e #d7f3ff",
                "status": "bg:#005f87 #ffffff bold",
            }
        ),
    ),
    "mono": Theme(
        name="mono",
        accent="white",
        success="white",
        warning="white",
        error="white",
        reasoning="white",
        prompt_style=Style.from_dict(
            {
                "frame.label": "bold",
                "text-area": "",
                "status": "reverse",
            }
        ),
    ),
    "high-contrast": Theme(
        name="high-contrast",
        accent="bright_white",
        success="bright_green",
        warning="bright_yellow",
        error="bright_red",
        reasoning="bright_magenta",
        prompt_style=Style.from_dict(
            {
                "frame.label": "bg:#000000 #ffffff bold",
                "text-area": "bg:#000000 #ffffff",
                "status": "bg:#ffffff #000000 bold",
            }
        ),
    ),
}


def get_theme(name: str | None) -> Theme:
    return THEMES.get(name or "default", THEMES["default"])
