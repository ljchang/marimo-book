"""Tests for `defaults.hide_author_line` (transforms/author_line.py)."""

from __future__ import annotations

import ast
import shutil
from pathlib import Path

import pytest

from marimo_book.transforms.author_line import (
    strip_author_line,
    strip_html_author_line,
    strip_markdown_author_line,
)
from marimo_book.transforms.wasm import strip_author_line_from_source

FIXTURES = Path(__file__).parent / "fixtures"
NOTEBOOK_FIXTURE = FIXTURES / "simple_notebook.py"


# --- the byline shapes books actually use ------------------------------------


@pytest.mark.parametrize(
    "byline",
    [
        "*Written by Luke Chang*",
        "_Written by Luke Chang_",
        "*Written by Luke Chang & Jin Cheong*",
        "*Written By: Clara Sava-Segal & Thomas L. Botch (edited by Luke Chang)*",
        "   *written by someone*   ",
    ],
)
def test_markdown_bylines_are_stripped(byline: str) -> None:
    body = f"# Title\n\n{byline}\n\nProse stays.\n"
    out = strip_markdown_author_line(body)
    assert "ritten" not in out
    assert "# Title" in out and "Prose stays." in out


@pytest.mark.parametrize(
    "html",
    [
        '<span class="paragraph"><em>Written by Luke Chang</em></span>',
        "<p><em>Written by Luke Chang &amp; Jin Cheong</em></p>",
    ],
)
def test_marimo_rendered_bylines_are_stripped(html: str) -> None:
    """A composite cell (`mo.vstack`) is rendered by marimo, not converted to
    Markdown, so the byline arrives as an italic paragraph element."""
    body = f'{html}<span class="paragraph">Prose stays.</span>'
    out = strip_html_author_line(body)
    assert "ritten by" not in out
    assert "Prose stays." in out


def test_prose_that_merely_mentions_an_author_is_kept() -> None:
    """Only a paragraph that is *entirely* the byline counts."""
    body = "This chapter was *written by* many hands, and the prose continues.\n"
    assert strip_author_line(body) == body


def test_only_the_first_byline_is_removed() -> None:
    body = "*Written by A*\n\ntext\n\n*Written by B*\n"
    out = strip_author_line(body)
    assert "Written by A" not in out
    assert "Written by B" in out


def test_a_page_without_a_byline_is_untouched() -> None:
    body = "# Title\n\nJust prose.\n"
    assert strip_author_line(body) == body


# --- the WASM path (source-level) ---------------------------------------------


def test_wasm_source_strip_edits_the_markdown_and_still_parses() -> None:
    """WASM prose is re-rendered in the browser from the islands payload, so
    the byline has to leave the source the runtime executes."""
    src = (
        "import marimo\n\napp = marimo.App()\n\n\n"
        "@app.cell\ndef _(mo):\n"
        '    mo.md(r"""\n    # Title\n\n    *Written by Luke Chang*\n\n    Prose stays.\n    """)\n'
        "    return\n"
    )
    out = strip_author_line_from_source(src)
    assert "Written by" not in out
    assert "Prose stays." in out
    ast.parse(out)  # must remain valid Python


def test_wasm_source_strip_is_a_noop_without_a_byline() -> None:
    src = NOTEBOOK_FIXTURE.read_text(encoding="utf-8")
    assert strip_author_line_from_source(src) == src


def test_wasm_source_strip_survives_unparsable_source() -> None:
    assert strip_author_line_from_source("def (:") == "def (:"


# --- end to end through a build -----------------------------------------------


def _book_with_byline(tmp_path: Path, *, hide: bool) -> tuple[Path, object]:
    from marimo_book.config import Book

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    src = NOTEBOOK_FIXTURE.read_text(encoding="utf-8").replace(
        "# Simple Notebook", "# Simple Notebook\n\n    *Written by A Person*", 1
    )
    (content / "nb.py").write_text(src, encoding="utf-8")
    book = Book.model_validate(
        {
            "title": "T",
            "toc": [{"file": "content/nb.py"}],
            "defaults": {"hide_author_line": hide},
        }
    )
    return tmp_path, book


def test_build_hides_the_byline_by_default(tmp_path: Path) -> None:
    from marimo_book.preprocessor import Preprocessor

    book_dir, book = _book_with_byline(tmp_path, hide=True)
    out = tmp_path / "_site_src"
    Preprocessor(book, book_dir=book_dir).build(out_dir=out)
    page = (out / "docs" / "index.md").read_text(encoding="utf-8")
    assert "Written by" not in page
    assert "Simple Notebook" in page


def test_build_keeps_the_byline_when_disabled(tmp_path: Path) -> None:
    from marimo_book.preprocessor import Preprocessor

    book_dir, book = _book_with_byline(tmp_path, hide=False)
    out = tmp_path / "_site_src"
    Preprocessor(book, book_dir=book_dir).build(out_dir=out)
    page = (out / "docs" / "index.md").read_text(encoding="utf-8")
    assert "Written by A Person" in page


def test_markdown_pages_keep_their_byline(tmp_path: Path) -> None:
    """The knob is documented for notebook cells; a hand-written .md page is
    the author's own markup and is left alone."""
    from marimo_book.config import Book
    from marimo_book.preprocessor import Preprocessor

    content = tmp_path / "content"
    content.mkdir()
    (content / "page.md").write_text(
        "# Page\n\n*Written by A Person*\n\nProse.\n", encoding="utf-8"
    )
    shutil.copy(NOTEBOOK_FIXTURE, content / "nb.py")
    book = Book.model_validate(
        {"title": "T", "toc": [{"file": "content/page.md"}, {"file": "content/nb.py"}]}
    )
    out = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out)
    assert "Written by A Person" in (out / "docs" / "index.md").read_text(encoding="utf-8")


# --- caching ------------------------------------------------------------------


def test_toggling_the_flag_does_not_invalidate_rendered_bodies(tmp_path: Path) -> None:
    """``_rendered/`` holds static-path bodies, where the byline is stripped at
    finalize time — so flipping the flag must not re-execute a `mode: cached`
    notebook (Download_Data in dartbrains is a ~46 GB download)."""
    from marimo_book.config import Book
    from marimo_book.preprocessor import _render_body_signature

    def book(hide: bool) -> Book:
        return Book.model_validate(
            {
                "title": "T",
                "toc": [{"file": "content/nb.py"}],
                "defaults": {"hide_author_line": hide},
            }
        )

    assert _render_body_signature(book(True)) == _render_body_signature(book(False))


def test_toggling_the_flag_does_invalidate_the_transient_cache(tmp_path: Path) -> None:
    """A WASM body bakes the byline in at the source level, and WASM bodies
    live in the transient cache — so that key must track the flag."""
    from marimo_book.config import Book
    from marimo_book.preprocessor import _book_signature

    def book(hide: bool) -> Book:
        return Book.model_validate(
            {
                "title": "T",
                "toc": [{"file": "content/nb.py", "mode": "wasm"}],
                "defaults": {"hide_author_line": hide},
            }
        )

    assert _book_signature(book(True), book_dir=tmp_path) != _book_signature(
        book(False), book_dir=tmp_path
    )
