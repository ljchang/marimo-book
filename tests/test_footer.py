"""The footer always credits marimo-book (alongside any user copyright)."""

from pathlib import Path

from marimo_book.config import Book
from marimo_book.shell import _build_config


def _cfg(**book_kwargs):
    book = Book(title="T", toc=[], **book_kwargs)
    return _build_config(
        book,
        docs_dir=Path("docs"),
        site_dir=Path("site"),
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )


def test_footer_credits_marimo_book():
    cfg = _cfg()
    assert "Marimo-Book" in cfg["copyright"]
    assert "marimobook.org" in cfg["copyright"]


def test_footer_prepends_user_copyright():
    cfg = _cfg(copyright="© 2022 Acme")
    assert cfg["copyright"].startswith("© 2022 Acme")
    assert "marimobook.org" in cfg["copyright"]


def test_molab_button_carries_the_marimo_mark() -> None:
    """The molab button should look like the row it sits in: a currentColor
    glyph, not the colour illustration molab uses as its own logo."""
    from marimo_book.config import Book
    from marimo_book.launch_buttons import render_button_row

    book = Book.model_validate(
        {"title": "T", "repo": "https://github.com/o/r", "toc": [{"file": "content/nb.py"}]}
    )
    row = render_button_row(book, Path("content/nb.py"))
    molab = row[row.index("marimo-book-button-molab") : row.index("marimo-book-button-github")]
    assert 'viewBox="487.8 369.1 224.42 231.84"' in molab  # marimo's mark, tightly boxed
    assert 'class="marimo-book-button-icon"' in molab
    assert "data:image" not in row, "no raster icons — they cannot take currentColor"
    assert "<img" not in row


def test_button_icons_are_all_the_same_shape() -> None:
    """Every glyph in the row takes its size and colour from the same class, so
    they line up whether the row sits in the page or is cloned into the header."""
    from marimo_book.config import Book
    from marimo_book.launch_buttons import render_button_row

    book = Book.model_validate(
        {"title": "T", "repo": "https://github.com/o/r", "toc": [{"file": "content/nb.py"}]}
    )
    row = render_button_row(book, Path("content/nb.py"))
    assert row.count('class="marimo-book-button-icon"') == 3  # molab, github, download
    assert row.count("<svg") == 3
