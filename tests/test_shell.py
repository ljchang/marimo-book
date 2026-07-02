"""Tests for the generated mkdocs.yml (shell.py)."""

from __future__ import annotations

from marimo_book.config import Book
from marimo_book.shell import _theme_block


def _book(**overrides) -> Book:
    data = {"title": "T", "toc": [{"file": "content/a.md"}], **overrides}
    return Book.model_validate(data)


def test_palettes_follow_system_color_scheme() -> None:
    palettes = _theme_block(_book())["palette"]
    media = {p["scheme"]: p.get("media") for p in palettes}
    assert media["default"] == "(prefers-color-scheme: light)"
    assert media["slate"] == "(prefers-color-scheme: dark)"
