"""Tests for src/marimo_book/blog.py — Tasks 2–6."""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import yaml  # noqa: F401  (used in Task 6 tests below)

from marimo_book.blog import parse_blog_block, parse_post_header, resolve_meta


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


def test_md_front_matter_parsed(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-04-hello.md"
    p.write_text("---\ntitle: Hello\nauthors: [luke]\n---\n\n# Body\n")
    meta = parse_post_header(p)
    assert meta.title == "Hello"
    assert meta.authors == ["luke"]
    assert meta.is_notebook is False


def test_date_defaults_from_filename(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-04-hello.md"
    p.write_text("---\ntitle: Hello\n---\n# Body\n")
    meta = resolve_meta(parse_post_header(p), p, default_author="luke")
    assert meta.date == _date(2026, 6, 4)
    assert meta.authors == ["luke"]


def test_title_falls_back_to_first_h1(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-04-x.md"
    p.write_text("---\ndate: 2026-06-04\n---\n\n# Real Title\n\nbody\n")
    meta = resolve_meta(parse_post_header(p), p, default_author=None)
    assert meta.title == "Real Title"
    assert meta.authors == []
