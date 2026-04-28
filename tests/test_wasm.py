"""End-to-end test for the WASM (marimo islands) render path.

The test runs the full Preprocessor.build() against a mode=wasm entry
and asserts the staged page contains marimo's island markup. This
exercises the marimo subprocess + asyncio path and takes a few seconds.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor
from marimo_book.transforms import wasm as wasm_module


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

    # Single-entry TOC: the only file is auto-promoted to index.md.
    staged = (out_dir / "docs" / "index.md").read_text(encoding="utf-8")
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

    # First TOC entry (intro.md) auto-promoted to index.md; demo.py stays put.
    intro = (out_dir / "docs" / "index.md").read_text(encoding="utf-8")
    assert "@marimo-team/islands" not in intro
    assert "# Intro" in intro

    demo = (out_dir / "docs" / "demo.md").read_text(encoding="utf-8")
    assert "@marimo-team/islands" in demo


def test_wasm_anywidgets_rewritten_to_static_mount(tmp_path: Path) -> None:
    """Anywidgets in a WASM-mode page get rewrapped as static mounts.

    Why: ``MarimoIslandGenerator`` runs under ``ScriptRuntimeContext``
    which hardcodes ``virtual_files_supported=False``, so every
    anywidget's ES module is emitted as a ``data:text/javascript;base64,…``
    URL. Marimo's islands runtime explicitly refuses to load those
    ("Refusing to load anywidget module from untrusted URL"), so
    anywidgets render as empty in WASM-mode pages by default.

    ``render_wasm_page`` post-processes the islands body with
    ``rewrite_anywidget_html`` so anywidgets become
    ``<div class="marimo-book-anywidget">`` mounts that
    ``marimo_book.js`` hydrates by importing the data URL directly.
    The cells themselves still go through marimo's runtime + Pyodide
    for full Python reactivity; only the anywidget modules are
    mounted by the static shim.
    """
    py_path = tmp_path / "demo.py"
    py_path.write_text(
        "import marimo\napp = marimo.App()\nif __name__ == '__main__': app.run()\n",
        encoding="utf-8",
    )

    fake_body = (
        '<marimo-island data-cell-id="abc">'
        "<marimo-anywidget data-js-url='\"data:text/javascript;base64,Zm9vCg==\"'"
        ' data-initial-value=\'{"model_id":"m1"}\' data-model-id="m1">'
        "</marimo-anywidget>"
        "</marimo-island>"
    )

    class _FakeGen:
        @staticmethod
        def from_file(path, *, display_code=False):  # noqa: ARG004
            return _FakeGen()

        async def build(self):
            pass

        def render_head(self):
            return '<script src="https://example/islands.js"></script>'

        def render_body(self, *, style="", include_init_island=True):  # noqa: ARG002
            return fake_body

    with patch.object(wasm_module, "MarimoIslandGenerator", _FakeGen):
        out = wasm_module.render_wasm_page(py_path)

    # The original <marimo-anywidget> tag is gone; the static mount is in.
    assert "<marimo-anywidget" not in out
    assert 'class="marimo-book-anywidget"' in out
    # The data URL is preserved on the new mount so the JS shim can import it.
    assert "data-js-url" in out
    assert "data:text/javascript;base64" in out
    # The surrounding <marimo-island> wrapper stays — cells still go through
    # marimo's islands runtime; only the anywidget child got rewrapped.
    assert "<marimo-island" in out
