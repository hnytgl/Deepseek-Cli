from __future__ import annotations

from deepseek_cli.theme import THEMES, get_theme


def test_builtin_themes_are_available() -> None:
    assert {"default", "ocean", "mono", "high-contrast"} <= set(THEMES)


def test_unknown_theme_falls_back_to_default() -> None:
    assert get_theme("unknown") == THEMES["default"]
