"""Tests for the generated mkdocs.yml (shell.py)."""

from __future__ import annotations

from pathlib import Path

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


def test_nav_features_include_prefetch_progress_and_top() -> None:
    features = _theme_block(_book())["features"]
    assert "navigation.instant.prefetch" in features
    assert "navigation.instant.progress" in features
    assert "navigation.top" in features


def test_mkdocs_shell_keeps_absolute_site_dir_and_no_variant(tmp_path) -> None:
    from marimo_book.shell import _build_config

    cfg = _build_config(
        _book(),
        docs_dir=Path("docs"),
        site_dir=tmp_path / "_site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert cfg["site_dir"] == str(tmp_path / "_site")
    assert "variant" not in cfg["theme"]


def test_zensical_shell_emits_relative_site_dir_and_classic_variant(tmp_path) -> None:
    """Zensical panics on absolute paths and rejects a site_dir outside its
    project root, so the config must point at a subdirectory of _site_src."""
    from marimo_book.shell import ZENSICAL_SITE_SUBDIR, _build_config

    cfg = _build_config(
        _book(shell="zensical"),
        docs_dir=Path("docs"),
        site_dir=tmp_path / "_site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert cfg["site_dir"] == ZENSICAL_SITE_SUBDIR
    assert not Path(cfg["site_dir"]).is_absolute()
    assert ".." not in cfg["site_dir"]
    assert cfg["docs_dir"] == "docs"
    assert cfg["theme"]["name"] == "material"
    assert cfg["theme"]["variant"] == "classic"


def test_umami_analytics_emits_custom_partial_config(tmp_path) -> None:
    from marimo_book.shell import _build_config

    cfg = _build_config(
        _book(
            analytics={
                "provider": "umami",
                "domain": "https://analytics.example.com/",
                "website_id": "website-id",
                "domains": ["docs.example.com"],
                "performance": True,
            }
        ),
        docs_dir=Path("docs"),
        site_dir=tmp_path / "_site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )

    assert cfg["theme"]["custom_dir"] == "docs/overrides"
    assert cfg["extra"]["analytics"] == {
        "provider": "umami",
        "property": None,
        "website_id": "website-id",
        "script_url": "https://analytics.example.com/script.js",
        "host_url": None,
        "domains": ["docs.example.com"],
        "tag": None,
        "auto_track": True,
        "auto_pageview": True,
        "performance": True,
        "exclude_search": False,
        "exclude_hash": False,
        "do_not_track": False,
    }
