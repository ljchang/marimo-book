"""Tests for the api_docs enumeration + staging module."""

from __future__ import annotations

from pathlib import Path

import pytest

from marimo_book.api_docs import resolve_search_paths, stage_api_docs
from marimo_book.config import ApiDocs

FIXTURES = Path(__file__).parent / "fixtures"


def _read(p: Path) -> str:
    return p.read_text(encoding="utf-8")


def test_resolve_search_paths_relative_to_book_root(tmp_path):
    cfg = ApiDocs(enabled=True, packages=["sample_pkg"], paths=[Path("src")])
    resolved = resolve_search_paths(cfg, tmp_path)
    assert resolved == [(tmp_path / "src").resolve()]


def test_stage_writes_one_page_per_public_module(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    cfg = ApiDocs(enabled=True, packages=["sample_pkg"])
    stage_api_docs(cfg, search_paths=[FIXTURES], docs_dir=docs_dir)

    assert "::: sample_pkg\n" in _read(docs_dir / "api/sample_pkg/index.md")
    assert "::: sample_pkg.core\n" in _read(docs_dir / "api/sample_pkg/core.md")
    assert "::: sample_pkg.sub\n" in _read(docs_dir / "api/sample_pkg/sub/index.md")
    assert "::: sample_pkg.sub.widgets\n" in _read(docs_dir / "api/sample_pkg/sub/widgets.md")
    # private module is skipped
    assert not (docs_dir / "api/sample_pkg/_private.md").exists()


def test_stage_returns_nested_nav(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    cfg = ApiDocs(enabled=True, packages=["sample_pkg"])
    nav = stage_api_docs(cfg, search_paths=[FIXTURES], docs_dir=docs_dir)

    assert nav == [
        {
            "API Reference": [
                {
                    "sample_pkg": [
                        "api/sample_pkg/index.md",
                        {"core": "api/sample_pkg/core.md"},
                        {
                            "sub": [
                                "api/sample_pkg/sub/index.md",
                                {"widgets": "api/sample_pkg/sub/widgets.md"},
                            ]
                        },
                    ]
                }
            ]
        }
    ]


def test_exclude_glob_skips_modules(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    cfg = ApiDocs(enabled=True, packages=["sample_pkg"], exclude=["sample_pkg.sub*"])
    stage_api_docs(cfg, search_paths=[FIXTURES], docs_dir=docs_dir)

    assert (docs_dir / "api/sample_pkg/core.md").exists()
    assert not (docs_dir / "api/sample_pkg/sub").exists()


def test_unknown_package_raises_clear_error(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    cfg = ApiDocs(enabled=True, packages=["does_not_exist_xyz"])
    with pytest.raises(RuntimeError, match="could not load package 'does_not_exist_xyz'"):
        stage_api_docs(cfg, search_paths=[FIXTURES], docs_dir=docs_dir)


def test_subpackage_with_all_children_excluded_collapses_to_leaf(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    # Exclude sub's *children* (sample_pkg.sub.widgets) but keep sub itself.
    # With no public children, sub must collapse to a single leaf page.
    cfg = ApiDocs(enabled=True, packages=["sample_pkg"], exclude=["sample_pkg.sub.*"])
    nav = stage_api_docs(cfg, search_paths=[FIXTURES], docs_dir=docs_dir)

    assert (docs_dir / "api/sample_pkg/sub.md").exists()
    assert not (docs_dir / "api/sample_pkg/sub/index.md").exists()
    assert nav == [
        {
            "API Reference": [
                {
                    "sample_pkg": [
                        "api/sample_pkg/index.md",
                        {"core": "api/sample_pkg/core.md"},
                        {"sub": "api/sample_pkg/sub.md"},
                    ]
                }
            ]
        }
    ]


def _book_with_api(**api_kwargs):
    from marimo_book.config import ApiDocs, Book

    return Book(
        title="T",
        toc=[],
        api_docs=ApiDocs(enabled=True, packages=["mypkg"], **api_kwargs),
    )


def test_mkdocstrings_plugin_emitted_when_enabled(tmp_path):
    from marimo_book.shell import _build_config

    book = _book_with_api(docstring_style="numpy", options={"members_order": "source"})
    cfg = _build_config(
        book,
        docs_dir=tmp_path / "docs",
        site_dir=tmp_path / "site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
        api_paths=["/abs/src"],
    )
    mkdocstrings = next(
        p["mkdocstrings"] for p in cfg["plugins"] if isinstance(p, dict) and "mkdocstrings" in p
    )
    opts = mkdocstrings["handlers"]["python"]["options"]
    assert opts["docstring_style"] == "numpy"
    assert opts["show_submodules"] is False
    assert opts["members_order"] == "source"  # user override merged in
    assert mkdocstrings["handlers"]["python"]["paths"] == ["/abs/src"]


def test_mkdocstrings_plugin_absent_when_disabled(tmp_path):
    from marimo_book.config import Book
    from marimo_book.shell import _build_config

    book = Book(title="T", toc=[])
    cfg = _build_config(
        book,
        docs_dir=tmp_path / "docs",
        site_dir=tmp_path / "site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert not any(isinstance(p, dict) and "mkdocstrings" in p for p in cfg["plugins"])
