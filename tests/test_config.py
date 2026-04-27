"""Schema-level tests for book.yml loading/validation."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from marimo_book.config import Book, FileEntry, SectionEntry, UrlEntry, load_book


def test_minimal_book_validates(tmp_path: Path) -> None:
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(yaml.safe_dump({"title": "Minimal", "toc": [{"file": "intro.md"}]}))
    book = load_book(book_yml)
    assert book.title == "Minimal"
    assert len(book.toc) == 1
    assert isinstance(book.toc[0], FileEntry)
    assert book.toc[0].file == Path("intro.md")


def test_nested_toc_discriminates_entries(tmp_path: Path) -> None:
    data = {
        "title": "Nested",
        "toc": [
            {"file": "intro.md"},
            {
                "section": "Course Overview",
                "children": [
                    {"file": "syllabus.md"},
                    {"url": "https://example.org", "title": "External"},
                ],
            },
        ],
    }
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(yaml.safe_dump(data))
    book = load_book(book_yml)

    assert isinstance(book.toc[0], FileEntry)
    assert isinstance(book.toc[1], SectionEntry)
    section = book.toc[1]
    assert isinstance(section.children[0], FileEntry)
    assert isinstance(section.children[1], UrlEntry)


def test_unknown_top_level_key_rejected(tmp_path: Path) -> None:
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(yaml.safe_dump({"title": "X", "toc": [{"file": "a.md"}], "ooga": 1}))
    with pytest.raises(ValidationError):
        load_book(book_yml)


def test_bibliography_list_shorthand(tmp_path: Path) -> None:
    """``bibliography: [a.bib, b.bib]`` should coerce into the Bibliography model."""
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(
        yaml.safe_dump(
            {
                "title": "Cited",
                "bibliography": ["refs.bib", "more.bib"],
                "toc": [{"file": "a.md"}],
            }
        )
    )
    book = load_book(book_yml)
    assert [str(p) for p in book.bibliography.files] == ["refs.bib", "more.bib"]


def test_launch_buttons_defaults() -> None:
    b = Book.model_validate({"title": "T", "toc": [{"file": "a.md"}]})
    assert b.launch_buttons.molab is True
    assert b.launch_buttons.github is True
    assert b.launch_buttons.download is True
    assert b.launch_buttons.wasm is False  # v0.2


def test_defaults_mode_static_or_wasm() -> None:
    """v0.2 added wasm; static stays the default."""
    b = Book.model_validate({"title": "T", "toc": [{"file": "a.md"}]})
    assert b.defaults.mode == "static"

    b_wasm = Book.model_validate(
        {"title": "T", "toc": [{"file": "a.md"}], "defaults": {"mode": "wasm"}}
    )
    assert b_wasm.defaults.mode == "wasm"

    # ``hybrid`` is reserved on the roadmap but not yet a valid value.
    with pytest.raises(ValidationError):
        Book.model_validate(
            {"title": "T", "toc": [{"file": "a.md"}], "defaults": {"mode": "hybrid"}}
        )


def test_file_entry_per_page_mode_override() -> None:
    """Per-entry ``mode`` overrides the book-wide default."""
    b = Book.model_validate(
        {
            "title": "T",
            "toc": [
                {"file": "a.py"},
                {"file": "b.py", "mode": "wasm"},
            ],
        }
    )
    a, b_entry = b.toc[0], b.toc[1]
    assert a.effective_mode("static") == "static"
    assert b_entry.effective_mode("static") == "wasm"
    # When the book default is wasm, an unset entry follows it.
    assert a.effective_mode("wasm") == "wasm"


def test_toc_entry_must_pick_one_shape() -> None:
    with pytest.raises(ValidationError):
        Book.model_validate({"title": "T", "toc": [{"unknown_kind": "oops"}]})


def test_defaults_suppress_warnings_round_trip() -> None:
    """``defaults.suppress_warnings`` is False by default and accepts True."""
    b = Book.model_validate({"title": "T", "toc": [{"file": "a.md"}]})
    assert b.defaults.suppress_warnings is False

    b_on = Book.model_validate(
        {
            "title": "T",
            "toc": [{"file": "a.md"}],
            "defaults": {"suppress_warnings": True},
        }
    )
    assert b_on.defaults.suppress_warnings is True
