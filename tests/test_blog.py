"""Tests for src/marimo_book/blog.py — Tasks 2–6."""

from __future__ import annotations

from marimo_book.blog import parse_blog_block


def test_parse_blog_block_reads_fields() -> None:
    src = (
        "# /// blog\n"
        '# title = "marimo-book 0.2 released"\n'
        "# date = 2026-06-04\n"
        '# authors = ["luke", "jane"]\n'
        '# tags = ["release"]\n'
        "# draft = true\n"
        "# ///\n"
        "import marimo\n"
    )
    meta = parse_blog_block(src)
    assert meta == {
        "title": "marimo-book 0.2 released",
        "date": "2026-06-04",
        "authors": ["luke", "jane"],
        "tags": ["release"],
        "draft": True,
    }


def test_parse_blog_block_absent_returns_none() -> None:
    assert parse_blog_block("import marimo\n") is None
