"""End-to-end tests for the Preprocessor's optional features."""

from __future__ import annotations

from pathlib import Path

import yaml

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor


def _minimal_book(book_dir: Path) -> None:
    """Lay down a minimal book at ``book_dir`` so Preprocessor.build runs."""
    (book_dir / "content").mkdir()
    (book_dir / "content" / "intro.md").write_text("# Intro\n\nHello.\n", encoding="utf-8")


def _book_config(*, include_changelog: bool) -> Book:
    return Book.model_validate(
        {
            "title": "Test",
            "include_changelog": include_changelog,
            "toc": [{"file": "content/intro.md"}],
        }
    )


def test_include_changelog_stages_file_and_appends_nav(tmp_path: Path) -> None:
    _minimal_book(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] — 2026-04-25\n\n- First release.\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=True), book_dir=tmp_path)
    pre.build(out_dir=out_dir)

    staged = out_dir / "docs" / "changelog.md"
    assert staged.exists(), "include_changelog should copy CHANGELOG.md to docs/changelog.md"
    assert "First release." in staged.read_text(encoding="utf-8")

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    nav_titles = [list(e.keys())[0] if isinstance(e, dict) else e for e in mkdocs["nav"]]
    assert "Changelog" in nav_titles, f"nav should include Changelog entry; got {nav_titles}"


def test_include_changelog_off_by_default(tmp_path: Path) -> None:
    _minimal_book(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    out_dir = tmp_path / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=False), book_dir=tmp_path)
    pre.build(out_dir=out_dir)

    assert not (out_dir / "docs" / "changelog.md").exists()
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    nav_titles = [list(e.keys())[0] if isinstance(e, dict) else e for e in mkdocs["nav"]]
    assert "Changelog" not in nav_titles


def test_include_changelog_finds_changelog_in_parent_dir(tmp_path: Path) -> None:
    """Common layout: book.yml in repo/docs/, CHANGELOG.md at repo root."""
    book_dir = tmp_path / "docs"
    book_dir.mkdir()
    _minimal_book(book_dir)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n- Found via parent fallback.\n", encoding="utf-8"
    )
    out_dir = book_dir / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=True), book_dir=book_dir)
    pre.build(out_dir=out_dir)

    staged = out_dir / "docs" / "changelog.md"
    assert staged.exists()
    assert "Found via parent fallback." in staged.read_text(encoding="utf-8")


def test_include_changelog_silent_when_no_file(tmp_path: Path) -> None:
    """Flag-on with no CHANGELOG.md is a no-op, not an error."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=True), book_dir=tmp_path)
    report = pre.build(out_dir=out_dir)

    assert not (out_dir / "docs" / "changelog.md").exists()
    assert not report.errors


def test_pdf_export_adds_with_pdf_plugin(tmp_path: Path) -> None:
    """`pdf_export: true` should append `with-pdf` to the generated plugins."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"
    book = Book.model_validate(
        {
            "title": "Test",
            "pdf_export": True,
            "toc": [{"file": "content/intro.md"}],
        }
    )

    pre = Preprocessor(book, book_dir=tmp_path)
    pre.build(out_dir=out_dir)

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    plugin_names = [next(iter(p.keys())) if isinstance(p, dict) else p for p in mkdocs["plugins"]]
    assert "with-pdf" in plugin_names
