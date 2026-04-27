"""End-to-end tests for the Preprocessor's optional features."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path

import yaml

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor

FIXTURES = Path(__file__).parent / "fixtures"
NOTEBOOK_FIXTURE = FIXTURES / "simple_notebook.py"


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


def test_first_toc_entry_promoted_to_index(tmp_path: Path) -> None:
    """The first TOC entry stages to docs/index.md so /index.html serves it.

    Without this, mkdocs's site root 404s and the header logo (which
    always links to /) takes the user nowhere.
    """
    content = tmp_path / "content"
    content.mkdir()
    (content / "intro.md").write_text("# Intro\n\nWelcome.\n", encoding="utf-8")
    (content / "next.md").write_text("# Next page\n", encoding="utf-8")
    book = Book.model_validate(
        {
            "title": "Test",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/next.md"},
            ],
        }
    )
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    # First entry promoted to index.md, original path NOT staged.
    assert (out_dir / "docs" / "index.md").exists()
    assert not (out_dir / "docs" / "intro.md").exists()
    # Subsequent entries unchanged.
    assert (out_dir / "docs" / "next.md").exists()
    # Nav references index.md, not intro.md.
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    assert "index.md" in mkdocs["nav"]
    assert "intro.md" not in mkdocs["nav"]


def test_empty_section_silently_skipped_in_nav(tmp_path: Path) -> None:
    """An empty section (no children) shouldn't crash and shouldn't render."""
    _minimal_book(tmp_path)
    book = Book.model_validate(
        {
            "title": "Test",
            "toc": [
                {"file": "content/intro.md"},
                # User stub with no children — common while drafting a TOC.
                {"section": "Coming soon", "children": None},
            ],
        }
    )
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    # Empty section should not appear in the nav.
    nav_labels = [next(iter(e.keys())) if isinstance(e, dict) else e for e in mkdocs["nav"]]
    assert "Coming soon" not in nav_labels


def test_logo_placement_sidebar_stages_stylesheet(tmp_path: Path) -> None:
    """`logo_placement: sidebar` should stage logo_sidebar.css and list it in extra_css."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"
    book = Book.model_validate(
        {
            "title": "Test",
            "logo_placement": "sidebar",
            "toc": [{"file": "content/intro.md"}],
        }
    )
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    assert (out_dir / "docs" / "stylesheets" / "logo_sidebar.css").exists()
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    assert "stylesheets/logo_sidebar.css" in mkdocs["extra_css"]


def test_logo_placement_header_omits_sidebar_stylesheet(tmp_path: Path) -> None:
    """Default header placement should not stage or reference logo_sidebar.css."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"
    book = Book.model_validate(
        {"title": "Test", "toc": [{"file": "content/intro.md"}]}
    )
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    assert not (out_dir / "docs" / "stylesheets" / "logo_sidebar.css").exists()
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    assert "stylesheets/logo_sidebar.css" not in mkdocs["extra_css"]


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


# --- BuildCache --------------------------------------------------------------
#
# These tests drive the preprocessor end-to-end against a real .py notebook
# fixture, so they invoke `marimo export ipynb` per build. ~2-3 seconds each
# on a warm machine; we run a tiny notebook fixture to keep them fast.


def _book_with_notebook(book_dir: Path) -> Book:
    """Lay down a book with one Markdown page and one notebook (the fixture)."""
    content = book_dir / "content"
    content.mkdir(exist_ok=True)
    (content / "intro.md").write_text("# Intro\n", encoding="utf-8")
    shutil.copy(NOTEBOOK_FIXTURE, content / "notebook.py")
    return Book.model_validate(
        {
            "title": "Cache Test",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/notebook.py"},
            ],
        }
    )


def _manifest(out_dir: Path, book_dir: Path) -> dict:
    return json.loads(
        (book_dir / ".marimo_book_cache" / "manifest.json").read_text(encoding="utf-8")
    )


def test_cache_cold_then_warm(tmp_path: Path) -> None:
    """First build renders + writes manifest; second build hits the cache."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"

    cold = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert cold.pages_rendered == 2  # intro.md + notebook.py
    assert cold.pages_cached == 0
    assert (tmp_path / ".marimo_book_cache" / "manifest.json").exists()

    warm = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    # .md still re-renders (not cached); .py is the only cache target.
    assert warm.pages_cached == 1
    assert warm.pages_rendered == 1


def test_cache_invalidates_on_source_change(tmp_path: Path) -> None:
    """Editing the notebook source forces a re-render of just that entry."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"

    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    nb = tmp_path / "content" / "notebook.py"
    # Bump mtime AND content so both fast-path and slow-path miss.
    time.sleep(0.01)
    nb.write_text(nb.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")

    second = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_rendered == 2  # intro.md (always) + notebook.py (invalidated)
    assert second.pages_cached == 0


def test_rebuild_flag_forces_full_render(tmp_path: Path) -> None:
    """`rebuild=True` skips the cache even when entries are valid."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"

    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    forced = Preprocessor(book, book_dir=tmp_path, rebuild=True).build(out_dir=out_dir)
    assert forced.pages_cached == 0
    assert forced.pages_rendered == 2


def test_cache_invalidates_on_tool_version_change(tmp_path: Path) -> None:
    """Bumping the recorded marimo_book_version invalidates the whole cache."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    manifest_path = tmp_path / ".marimo_book_cache" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["marimo_book_version"] = "0.0.0+impossible"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    second = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_cached == 0
    assert second.pages_rendered == 2


def test_cache_invalidates_on_widget_defaults_change(tmp_path: Path) -> None:
    """Editing widget_defaults in book.yml invalidates rendered notebooks."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    book2 = Book.model_validate(
        {
            "title": "Cache Test",
            "widget_defaults": {"FakeWidget": {"x": 1}},
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/notebook.py"},
            ],
        }
    )
    second = Preprocessor(book2, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_cached == 0
    assert second.pages_rendered == 2


def test_cache_invalidates_when_staged_output_missing(tmp_path: Path) -> None:
    """If someone wipes _site_src but leaves the cache, we must re-render."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    # Wipe the staged tree but leave the manifest alone.
    shutil.rmtree(out_dir)
    second = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_cached == 0
    assert second.pages_rendered == 2
