"""End-to-end test for the WASM (marimo islands) render path.

The test runs the full Preprocessor.build() against a mode=wasm entry
and asserts the staged page contains marimo's island markup. This
exercises the marimo subprocess + asyncio path and takes a few seconds.
"""

from __future__ import annotations

from pathlib import Path

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor


def _wasm_book(book_dir: Path) -> Book:
    """Tiny notebook with one slider, opted into WASM via the TOC entry."""
    content = book_dir / "content"
    content.mkdir()
    (content / "demo.py").write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    n = mo.ui.slider(1, 10, value=5)\n"
        "    n\n"
        "    return (n,)\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    return Book.model_validate(
        {
            "title": "Test",
            "toc": [{"file": "content/demo.py", "mode": "wasm"}],
        }
    )


def test_wasm_page_contains_island_markup(tmp_path: Path) -> None:
    book = _wasm_book(tmp_path)
    out_dir = tmp_path / "_site_src"

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report.errors
    assert report.pages == 1

    staged = (out_dir / "docs" / "demo.md").read_text(encoding="utf-8")
    # Marimo's CDN scripts injected at the top of the page body.
    assert "@marimo-team/islands" in staged
    # Each cell becomes a <marimo-island>.
    assert "<marimo-island" in staged
    # The slider becomes a marimo-slider web component (interactive).
    assert "marimo-slider" in staged or "marimo-ui-element" in staged


def test_wasm_page_skips_precompute(tmp_path: Path) -> None:
    """Precompute is a no-op for WASM pages; marimo's runtime handles reactivity."""
    book = _wasm_book(tmp_path)
    # Enable precompute. WASM page should NOT trigger any precompute warnings.
    payload = book.model_dump(mode="json")
    payload["precompute"] = {"enabled": True}
    book = Book.model_validate(payload)

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 0


def test_static_page_unchanged_alongside_wasm_entry(tmp_path: Path) -> None:
    """Adding a wasm entry to the TOC doesn't disturb static-mode entries."""
    content = tmp_path / "content"
    content.mkdir()
    (content / "intro.md").write_text("# Intro\n", encoding="utf-8")
    (content / "demo.py").write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell\n"
        "def _():\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/demo.py", "mode": "wasm"},
            ],
        }
    )
    out_dir = tmp_path / "_site_src"
    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report.errors

    intro = (out_dir / "docs" / "intro.md").read_text(encoding="utf-8")
    assert "@marimo-team/islands" not in intro
    assert "# Intro" in intro

    demo = (out_dir / "docs" / "demo.md").read_text(encoding="utf-8")
    assert "@marimo-team/islands" in demo
