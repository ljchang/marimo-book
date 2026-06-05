"""Tests for the api_docs enumeration + staging module."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from marimo_book.api_docs import resolve_search_paths, stage_api_docs
from marimo_book.config import ApiDocs, Book
from marimo_book.preprocessor import Preprocessor

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


def test_dotted_package_name_maps_to_path_and_keeps_full_label(tmp_path):
    docs_dir = tmp_path / "docs"
    docs_dir.mkdir()
    cfg = ApiDocs(enabled=True, packages=["sample_pkg.sub"])
    nav = stage_api_docs(cfg, search_paths=[FIXTURES], docs_dir=docs_dir)

    # Directory layout uses path segments, not a literal dotted dir.
    assert (docs_dir / "api/sample_pkg/sub/index.md").exists()
    assert (docs_dir / "api/sample_pkg/sub/widgets.md").exists()
    assert not (docs_dir / "api/sample_pkg.sub").exists()
    # Top-level nav key is the FULL dotted name (prevents same-last-segment collisions).
    section = nav[0]["API Reference"]
    assert list(section[0].keys()) == ["sample_pkg.sub"]
    assert section[0]["sample_pkg.sub"][0] == "api/sample_pkg/sub/index.md"


def _book_with_api(**api_kwargs):
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


def test_navigation_indexes_enabled_with_api_docs(tmp_path):
    # api_docs stages a section-index page per package; navigation.indexes
    # renders it as the section landing instead of a redundant child entry.
    from marimo_book.shell import _build_config

    on = _build_config(
        _book_with_api(),
        docs_dir=tmp_path / "docs",
        site_dir=tmp_path / "site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert "navigation.indexes" in on["theme"]["features"]

    off = _build_config(
        Book(title="T", toc=[]),
        docs_dir=tmp_path / "docs",
        site_dir=tmp_path / "site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert "navigation.indexes" not in off["theme"]["features"]


def test_mkdocstrings_inventories_passthrough(tmp_path):
    from marimo_book.shell import _build_config

    book = _book_with_api(inventories=["https://docs.python.org/3/objects.inv"])
    cfg = _build_config(
        book,
        docs_dir=tmp_path / "docs",
        site_dir=tmp_path / "site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    handler = next(
        p["mkdocstrings"]["handlers"]["python"]
        for p in cfg["plugins"]
        if isinstance(p, dict) and "mkdocstrings" in p
    )
    assert handler["inventories"] == ["https://docs.python.org/3/objects.inv"]

    # Omitted when empty (default).
    book2 = _book_with_api()
    cfg2 = _build_config(
        book2,
        docs_dir=tmp_path / "docs",
        site_dir=tmp_path / "site",
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    handler2 = next(
        p["mkdocstrings"]["handlers"]["python"]
        for p in cfg2["plugins"]
        if isinstance(p, dict) and "mkdocstrings" in p
    )
    assert "inventories" not in handler2


def test_preprocessor_stages_api_section(tmp_path):
    # Minimal book that documents the sample_pkg fixture by path.
    book_dir = tmp_path / "book"
    (book_dir / "content").mkdir(parents=True)
    (book_dir / "content" / "intro.md").write_text("# Intro\n", encoding="utf-8")

    book = Book.model_validate(
        {
            "title": "T",
            "toc": [{"file": "content/intro.md"}],
            "api_docs": {
                "enabled": True,
                "packages": ["sample_pkg"],
                "paths": [str(FIXTURES)],
            },
        }
    )

    out_dir = tmp_path / "_site_src"
    pre = Preprocessor(book, book_dir=book_dir)
    pre.build(out_dir=out_dir)

    docs_dir = out_dir / "docs"
    assert (docs_dir / "api/sample_pkg/index.md").exists()
    assert (docs_dir / "api/sample_pkg/core.md").exists()

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text())
    assert any(isinstance(p, dict) and "mkdocstrings" in p for p in mkdocs["plugins"])
    # nav contains the API Reference section
    assert any(isinstance(n, dict) and "API Reference" in n for n in mkdocs["nav"])
    # paths in the plugin are absolute
    plugin = next(p for p in mkdocs["plugins"] if isinstance(p, dict) and "mkdocstrings" in p)
    paths = plugin["mkdocstrings"]["handlers"]["python"]["paths"]
    assert all(Path(p).is_absolute() for p in paths)
