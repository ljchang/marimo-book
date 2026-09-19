"""Assignments sourced from the grader: ``grader:`` + ``assignment: <slug>``."""

from __future__ import annotations

import urllib.error
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from marimo_book import assignments
from marimo_book.assignments import AssignmentError, is_slug, resolve_assignment
from marimo_book.config import load_book

STUDENT = b"""# /// script
# dependencies = ["marimo", "marimo-grader-client"]
# grader-server = "https://grader.example.edu"
# grader-assignment = "glm"
# grader-version = "4"
# ///
import marimo

app = marimo.App()
"""


def _book(tmp_path: Path, *, grader: bool = True, assignment: str = "glm"):
    (tmp_path / "content").mkdir(exist_ok=True)
    (tmp_path / "content" / "ch.py").write_text("import marimo\napp = marimo.App()\n")
    data: dict = {
        "title": "T",
        "toc": [{"file": "content/ch.py", "assignment": assignment}],
    }
    if grader:
        data["grader"] = {
            "server": "https://grader.example.edu/",
            "course": "neuroimaging",
            "term": "2026-fall",
        }
    (tmp_path / "book.yml").write_text(yaml.safe_dump(data))
    book = load_book(tmp_path / "book.yml")
    return book, book.toc[0]


def _fake_download(calls: list[str], *, version: str | None = "4", fail: bool = False):
    def download(url: str, *, timeout: float = 30):
        calls.append(url)
        if fail:
            raise urllib.error.URLError("no route to host")
        headers = {"x-grader-version": version} if version else {}
        return STUDENT, headers

    return download


# --------------------------------------------------------------------------


def test_grader_section_normalises_the_server(tmp_path: Path) -> None:
    book, _ = _book(tmp_path)
    assert book.grader is not None
    assert book.grader.server == "https://grader.example.edu"  # trailing slash dropped
    assert book.grader.tool_table() == {
        "server": "https://grader.example.edu",
        "course": "neuroimaging",
        "term": "2026-fall",
    }


def test_grader_section_rejects_bad_values(tmp_path: Path) -> None:
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "ch.py").write_text("import marimo\n")
    for grader in (
        {"server": "grader.example.edu", "course": "c", "term": "t"},
        {"server": "https://x", "course": "a/b", "term": "t"},
    ):
        (tmp_path / "book.yml").write_text(
            yaml.safe_dump({"title": "T", "grader": grader, "toc": [{"file": "content/ch.py"}]})
        )
        with pytest.raises(ValidationError):
            load_book(tmp_path / "book.yml")


def test_is_slug() -> None:
    assert is_slug("glm") and is_slug("glm-single-subject")
    assert not is_slug("content/assignments/glm.py")
    assert not is_slug("glm.py")
    assert not is_slug("assignments/glm")


def test_a_committed_file_still_wins(tmp_path: Path) -> None:
    book, entry = _book(tmp_path, assignment="content/assignments/glm.py")
    (tmp_path / "content" / "assignments").mkdir()
    (tmp_path / "content" / "assignments" / "glm.py").write_bytes(STUDENT)
    asg = resolve_assignment(entry, book, tmp_path)
    assert asg.src == (tmp_path / "content" / "assignments" / "glm.py").resolve()
    assert asg.rel == Path("content/assignments/glm.py")
    assert asg.slug is None and asg.molab_url is None


def test_a_slug_is_fetched_from_the_grader_and_cached(tmp_path: Path, monkeypatch) -> None:
    calls: list[str] = []
    monkeypatch.setattr(assignments, "_download", _fake_download(calls))
    book, entry = _book(tmp_path)
    asg = resolve_assignment(entry, book, tmp_path)
    assert calls == ["https://grader.example.edu/a/neuroimaging/2026-fall/glm/student.py"]
    assert asg.slug == "glm" and asg.version == "4"
    assert asg.molab_url == "https://grader.example.edu/a/neuroimaging/2026-fall/glm/molab"
    assert asg.rel == Path("assignments/glm.py")
    cache = (
        tmp_path / ".marimo_book_cache" / "assignments" / "neuroimaging" / "2026-fall" / "glm.py"
    )
    assert asg.src == cache and cache.read_bytes() == STUDENT
    assert asg.notes == ()

    # Without fetching, the cached copy (and its version) is what you get.
    again = resolve_assignment(entry, book, tmp_path, fetch=False)
    assert again.src == cache and again.version == "4"


def test_a_slug_without_a_grader_section_is_an_error(tmp_path: Path) -> None:
    book, entry = _book(tmp_path, grader=False)
    with pytest.raises(AssignmentError, match="no `grader:` section"):
        resolve_assignment(entry, book, tmp_path)


def test_a_missing_file_that_is_not_a_slug_is_an_error(tmp_path: Path) -> None:
    book, entry = _book(tmp_path, assignment="content/assignments/nope.py")
    with pytest.raises(AssignmentError, match="missing file"):
        resolve_assignment(entry, book, tmp_path)


def test_offline_uses_the_cached_copy_with_a_note(tmp_path: Path, monkeypatch) -> None:
    book, entry = _book(tmp_path)
    monkeypatch.setattr(assignments, "_download", _fake_download([]))
    first = resolve_assignment(entry, book, tmp_path)
    monkeypatch.setattr(assignments, "_download", _fake_download([], fail=True))
    offline = resolve_assignment(entry, book, tmp_path)
    assert offline.src == first.src and offline.version == "4"
    assert len(offline.notes) == 1 and "unreachable" in offline.notes[0]


def test_offline_without_a_cached_copy_is_an_error(tmp_path: Path, monkeypatch) -> None:
    book, entry = _book(tmp_path)
    monkeypatch.setattr(assignments, "_download", _fake_download([], fail=True))
    with pytest.raises(AssignmentError, match="no cached copy"):
        resolve_assignment(entry, book, tmp_path)


# --------------------------------------------------------------------------


def test_check_never_fetches_and_reports_a_missing_grader(tmp_path: Path, monkeypatch) -> None:
    from marimo_book.checks import run_checks

    calls: list[str] = []
    monkeypatch.setattr(assignments, "_download", _fake_download(calls))
    book, entry = _book(tmp_path)
    # Fresh runner, nothing cached: check leaves the slug to the build.
    report = run_checks(book, tmp_path)
    assert calls == [] and not [e for e in report.errors if "assignment" in e], report.errors
    # Once the build has fetched it, check reads the cached copy (still no network).
    resolve_assignment(entry, book, tmp_path)
    report = run_checks(book, tmp_path)
    assert len(calls) == 1 and not [e for e in report.errors if "assignment" in e]

    book, _ = _book(tmp_path, grader=False)
    report = run_checks(book, tmp_path)
    assert any("no `grader:` section" in e for e in report.errors), report.errors


def test_sync_deps_writes_tool_grader_idempotently() -> None:
    from marimo_book.transforms.pep723 import write_pep723_block

    src = "import marimo\nimport numpy as np\n"
    tool = {"grader": {"server": "https://g", "course": "c", "term": "t"}}
    once = write_pep723_block(src, ["marimo", "numpy"], requires_python=">=3.11", tool=tool)
    assert "[tool.grader]" in once and 'server = "https://g"' in once
    twice = write_pep723_block(once, ["marimo", "numpy"], requires_python=">=3.11", tool=tool)
    assert twice == once
    # Other tool tables survive; the grader table is replaced, not merged.
    with_uv = write_pep723_block(
        src, ["marimo"], tool={"uv": {"exclude-newer": "2026-01-01"}, "grader": tool["grader"]}
    )
    changed = write_pep723_block(
        with_uv, ["marimo"], tool={"grader": {"server": "https://g", "course": "c", "term": "t2"}}
    )
    assert "exclude-newer" in changed and 'term = "t2"' in changed and 'term = "t"\n' not in changed


def test_card_links_to_molab_when_grader_sourced() -> None:
    from marimo_book.workbench import read_assignment_info, render_assignment_tail

    info = read_assignment_info(
        STUDENT.decode(),
        file=Path("assignments/glm.py"),
        nb_url="u",
        published_hash="h",
        molab_url="https://grader.example.edu/a/neuroimaging/2026-fall/glm/molab",
    )
    html = render_assignment_tail(info, rel_under_docs=Path("ch.md"))
    assert 'href="https://grader.example.edu/a/neuroimaging/2026-fall/glm/molab"' in html
    assert "Open in molab" in html
    plain = read_assignment_info(
        STUDENT.decode(), file=Path("a.py"), nb_url="u", published_hash="h"
    )
    assert "Open in molab" not in render_assignment_tail(plain, rel_under_docs=Path("ch.md"))
