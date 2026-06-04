"""Tests for src/marimo_book/blog.py — Tasks 2–6."""

from __future__ import annotations

from datetime import date as _date
from pathlib import Path

import yaml

from marimo_book.blog import (
    PostMeta,
    author_id,
    build_author_roster,
    discover_posts,
    insert_teaser,
    parse_blog_block,
    parse_post_header,
    render_front_matter,
    resolve_meta,
)
from marimo_book.config import Author


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


def test_author_id_slugifies() -> None:
    assert author_id("Luke Chang") == "luke-chang"
    assert author_id("Jane Q. Doe") == "jane-q-doe"


def test_roster_from_book_authors_only() -> None:
    roster = build_author_roster([Author(name="Luke Chang")], authors_yml=None)
    assert "luke-chang" in roster
    assert roster["luke-chang"]["name"] == "Luke Chang"


def test_authors_yml_overrides_on_collision() -> None:
    book_authors = [Author(name="Luke Chang", affiliation="Dartmouth")]
    yml = {"authors": {"luke-chang": {"name": "Luke C.", "description": "Maintainer"}}}
    roster = build_author_roster(book_authors, authors_yml=yml)
    assert roster["luke-chang"]["name"] == "Luke C."
    assert roster["luke-chang"]["description"] == "Maintainer"


MORE = "<!-- more -->"


def test_explicit_marker_preserved() -> None:
    md = "Intro.\n<!-- more -->\nRest.\n"
    assert insert_teaser(md) == md


def test_inserts_after_first_paragraph() -> None:
    md = "First para.\n\nSecond para.\n\nThird.\n"
    out = insert_teaser(md)
    assert out.count(MORE) == 1
    assert out.index(MORE) < out.index("Second para.")


def test_inserts_after_leading_heading_block() -> None:
    md = "# Title\n\nFirst para.\n\nSecond.\n"
    out = insert_teaser(md)
    assert out.index(MORE) < out.index("Second.")
    assert out.index("# Title") < out.index(MORE)


def test_discover_posts_finds_md_and_py(tmp_path: Path) -> None:
    posts = tmp_path / "blog" / "posts"
    posts.mkdir(parents=True)
    (posts / "2026-06-04-a.md").write_text("---\ndate: 2026-06-04\n---\nx\n")
    (posts / "2026-06-03-b.py").write_text(
        "# /// blog\n# date = 2026-06-03\n# ///\nimport marimo\n"
    )
    (posts / "ignore.txt").write_text("nope")
    found = sorted(p.name for p in discover_posts(tmp_path / "blog"))
    assert found == ["2026-06-03-b.py", "2026-06-04-a.md"]


def test_render_front_matter_round_trips() -> None:
    meta = PostMeta(title="Hi", date=_date(2026, 6, 4), authors=["luke"], tags=["release"])
    fm = render_front_matter(meta)
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    loaded = yaml.safe_load(fm.strip("-\n"))
    assert loaded["title"] == "Hi"
    assert loaded["date"] == _date(2026, 6, 4)
    assert loaded["authors"] == ["luke"]
