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
