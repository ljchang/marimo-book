"""Integration tests for ``marimo-book new`` and ``marimo-book clean``."""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from marimo_book.cli import app


@pytest.fixture
def runner() -> CliRunner:
    return CliRunner()


# --- new --------------------------------------------------------------------


def test_new_creates_expected_files(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "mybook"
    result = runner.invoke(app, ["new", str(target)])
    assert result.exit_code == 0, result.output
    assert (target / "book.yml").is_file()
    assert (target / "content" / "intro.md").is_file()
    assert (target / "content" / "example.py").is_file()
    assert (target / "README.md").is_file()
    assert (target / ".gitignore").is_file()
    assert (target / ".github" / "workflows" / "deploy.yml").is_file()


def test_new_scaffolded_book_validates(runner: CliRunner, tmp_path: Path) -> None:
    """A freshly-scaffolded book must pass `marimo-book check`."""
    target = tmp_path / "mybook"
    create = runner.invoke(app, ["new", str(target)])
    assert create.exit_code == 0

    check = runner.invoke(app, ["check", "-b", str(target / "book.yml")])
    assert check.exit_code == 0, check.output


def test_new_refuses_existing_non_empty_dir(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "some_file.txt").write_text("hi")
    result = runner.invoke(app, ["new", str(target)])
    assert result.exit_code == 2
    assert "already exists and is not empty" in result.output


def test_new_accepts_empty_existing_dir(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "empty"
    target.mkdir()
    result = runner.invoke(app, ["new", str(target)])
    assert result.exit_code == 0
    assert (target / "book.yml").is_file()


def test_new_force_overrides_non_empty_dir(runner: CliRunner, tmp_path: Path) -> None:
    target = tmp_path / "existing"
    target.mkdir()
    (target / "some_file.txt").write_text("hi")
    result = runner.invoke(app, ["new", str(target), "--force"])
    assert result.exit_code == 0
    assert (target / "book.yml").is_file()
    # pre-existing files stay untouched
    assert (target / "some_file.txt").read_text() == "hi"


# --- clean ------------------------------------------------------------------


def _make_dummy_book(tmp_path: Path) -> Path:
    """Write a minimal book.yml and fake build artifacts."""
    (tmp_path / "book.yml").write_text("title: T\ntoc:\n  - file: content/x.md\n")
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "x.md").write_text("# x")
    # Fake build artifacts
    (tmp_path / "_site").mkdir()
    (tmp_path / "_site" / "index.html").write_text("<html></html>")
    (tmp_path / "_site_src").mkdir()
    (tmp_path / "_site_src" / "mkdocs.yml").write_text("site_name: T")
    (tmp_path / ".marimo_book_cache").mkdir()
    return tmp_path / "book.yml"


def test_clean_removes_all_build_dirs(runner: CliRunner, tmp_path: Path) -> None:
    book_file = _make_dummy_book(tmp_path)
    result = runner.invoke(app, ["clean", "-b", str(book_file)])
    assert result.exit_code == 0, result.output
    assert not (tmp_path / "_site").exists()
    assert not (tmp_path / "_site_src").exists()
    assert not (tmp_path / ".marimo_book_cache").exists()
    assert "Cleaned 3 directorie(s)." in result.output


def test_clean_with_nothing_to_remove(runner: CliRunner, tmp_path: Path) -> None:
    (tmp_path / "book.yml").write_text("title: T\ntoc:\n  - file: content/x.md\n")
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "x.md").write_text("")
    result = runner.invoke(app, ["clean", "-b", str(tmp_path / "book.yml")])
    assert result.exit_code == 0
    assert "Nothing to clean." in result.output


def test_clean_leaves_content_and_book_yml(runner: CliRunner, tmp_path: Path) -> None:
    """Clean must never touch source files — only build outputs."""
    book_file = _make_dummy_book(tmp_path)
    result = runner.invoke(app, ["clean", "-b", str(book_file)])
    assert result.exit_code == 0
    assert book_file.exists()
    assert (tmp_path / "content" / "x.md").exists()


# --- sync-deps --------------------------------------------------------------


def _make_book_with_notebook(tmp_path: Path, source: str) -> Path:
    """Lay down a minimal book with one ``.py`` notebook entry; return book.yml path."""
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "nb.py").write_text(source, encoding="utf-8")
    book_yml = tmp_path / "book.yml"
    book_yml.write_text("title: T\ntoc:\n  - file: content/nb.py\n", encoding="utf-8")
    return book_yml


def test_sync_deps_adds_block_to_bare_notebook(runner: CliRunner, tmp_path: Path) -> None:
    """A notebook without a PEP 723 block gets one written in place."""
    book_yml = _make_book_with_notebook(
        tmp_path, "import marimo as mo\nimport numpy\nimport pandas\n"
    )
    result = runner.invoke(app, ["sync-deps", "-b", str(book_yml)])
    assert result.exit_code == 0, result.output
    rewritten = (tmp_path / "content" / "nb.py").read_text(encoding="utf-8")
    assert rewritten.startswith("# /// script\n")
    assert '"numpy"' in rewritten
    assert '"pandas"' in rewritten
    # marimo itself is excluded from the dependency list (provided by runtime).
    assert '"marimo"' not in rewritten


def test_sync_deps_check_exits_nonzero_when_block_missing(
    runner: CliRunner, tmp_path: Path
) -> None:
    """``--check`` must not modify files and must signal divergence via exit code."""
    book_yml = _make_book_with_notebook(tmp_path, "import numpy\n")
    before = (tmp_path / "content" / "nb.py").read_text(encoding="utf-8")
    result = runner.invoke(app, ["sync-deps", "-b", str(book_yml), "--check"])
    assert result.exit_code == 1
    assert "would update" in result.output
    after = (tmp_path / "content" / "nb.py").read_text(encoding="utf-8")
    assert after == before, "--check must not modify files"


def test_sync_deps_check_passes_when_already_up_to_date(runner: CliRunner, tmp_path: Path) -> None:
    """Idempotency: running sync-deps then --check yields exit 0."""
    book_yml = _make_book_with_notebook(tmp_path, "import marimo as mo\nimport numpy\n")
    first = runner.invoke(app, ["sync-deps", "-b", str(book_yml)])
    assert first.exit_code == 0
    second = runner.invoke(app, ["sync-deps", "-b", str(book_yml), "--check"])
    assert second.exit_code == 0, second.output


def test_sync_deps_preserves_existing_block_keys(runner: CliRunner, tmp_path: Path) -> None:
    """Hand-curated ``[tool.uv]`` and ``requires-python`` survive a sync."""
    source = """# /// script
# requires-python = ">=3.12"
# dependencies = [
#     "numpy",
# ]
#
# [tool.uv]
# extra-index-url = ["https://example/"]
# ///

import numpy
import pandas
"""
    book_yml = _make_book_with_notebook(tmp_path, source)
    result = runner.invoke(app, ["sync-deps", "-b", str(book_yml)])
    assert result.exit_code == 0, result.output
    rewritten = (tmp_path / "content" / "nb.py").read_text(encoding="utf-8")
    assert 'requires-python = ">=3.12"' in rewritten
    assert "[tool.uv]" in rewritten
    assert "https://example/" in rewritten
    assert '"pandas"' in rewritten


def test_sync_deps_no_py_notebooks_in_toc(runner: CliRunner, tmp_path: Path) -> None:
    """A book with only Markdown entries is a no-op (informational message)."""
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "intro.md").write_text("# x")
    book_yml = tmp_path / "book.yml"
    book_yml.write_text("title: T\ntoc:\n  - file: content/intro.md\n")
    result = runner.invoke(app, ["sync-deps", "-b", str(book_yml)])
    assert result.exit_code == 0
    assert "No marimo .py notebooks" in result.output
