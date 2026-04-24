"""Tests for the watcher's path-filtering and debouncing."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest
import yaml

from marimo_book.watcher import RebuildHandler


@pytest.fixture
def book_tree(tmp_path: Path) -> Path:
    """Minimal book_dir with content/, book.yml, and a dummy page."""
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "intro.md").write_text("# Intro")
    (tmp_path / "book.yml").write_text(
        yaml.safe_dump({"title": "T", "toc": [{"file": "content/intro.md"}]})
    )
    return tmp_path


def _make_handler(book_tree: Path) -> RebuildHandler:
    return RebuildHandler(
        book_file=book_tree / "book.yml",
        book_dir=book_tree,
        site_src=book_tree / "_site_src",
        debounce_seconds=0.05,
    )


def test_tracks_md_in_content(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    assert h._is_tracked(book_tree / "content" / "intro.md")


def test_tracks_py_in_content(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    (book_tree / "content" / "x.py").write_text("")
    assert h._is_tracked(book_tree / "content" / "x.py")


def test_tracks_book_yml_at_root(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    assert h._is_tracked(book_tree / "book.yml")


def test_ignores_files_outside_content(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    (book_tree / "notes.md").write_text("")
    assert not h._is_tracked(book_tree / "notes.md")


def test_ignores_marimo_cache_dir(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    cache = book_tree / "content" / "__marimo__" / "session" / "intro.py.json"
    cache.parent.mkdir(parents=True)
    cache.write_text("{}")
    assert not h._is_tracked(cache)


def test_ignores_pycache(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    p = book_tree / "content" / "__pycache__" / "x.pyc"
    p.parent.mkdir(parents=True)
    p.write_text("")
    assert not h._is_tracked(p)


def test_ignores_non_tracked_suffix(book_tree: Path) -> None:
    h = _make_handler(book_tree)
    p = book_tree / "content" / "output.nii.gz"
    p.write_text("")
    # ``.nii.gz`` ends with ``.gz`` suffix — not tracked.
    assert not h._is_tracked(p)


def test_debounces_rapid_events(book_tree: Path) -> None:
    """Rapid events fire a single rebuild, not one per event."""
    h = _make_handler(book_tree)
    rebuilds: list[int] = []
    h.on_report = lambda _report: rebuilds.append(1)

    # Fire 20 events in quick succession.
    fake_event = MagicMock()
    fake_event.is_directory = False
    fake_event.src_path = str(book_tree / "content" / "intro.md")
    fake_event.dest_path = None
    for _ in range(20):
        h.on_modified(fake_event)

    # Wait for the debounce timer to fire (0.05s debounce + slack).
    deadline = time.time() + 1.0
    while len(rebuilds) == 0 and time.time() < deadline:
        time.sleep(0.01)

    # Exactly one rebuild should have fired despite 20 events.
    assert len(rebuilds) == 1, f"expected 1 rebuild, got {len(rebuilds)}"


def test_handler_reports_validation_error_on_bad_book_yml(book_tree: Path) -> None:
    """Malformed book.yml should surface as a BuildReport error, not a crash."""
    # Corrupt book.yml before triggering rebuild.
    (book_tree / "book.yml").write_text("not: a valid: book\n  :")
    h = _make_handler(book_tree)
    captured: list = []
    h.on_report = captured.append

    # Directly invoke _rebuild to bypass the debounce timer.
    h._rebuild()

    assert len(captured) == 1
    assert not captured[0].ok
    assert any("book.yml" in e for e in captured[0].errors)
