"""Tests for the dependencies config + sandbox plumbing."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from marimo_book.config import Book, load_book
from marimo_book.preprocessor import Preprocessor
from marimo_book.transforms import marimo_export


def test_dependencies_defaults_to_env() -> None:
    b = Book.model_validate({"title": "T", "toc": [{"file": "a.md"}]})
    assert b.dependencies.mode == "env"


def test_dependencies_mode_sandbox(tmp_path: Path) -> None:
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(
        yaml.safe_dump(
            {
                "title": "T",
                "toc": [{"file": "a.md"}],
                "dependencies": {"mode": "sandbox"},
            }
        )
    )
    book = load_book(book_yml)
    assert book.dependencies.mode == "sandbox"


def test_dependencies_mode_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        Book.model_validate(
            {"title": "T", "toc": [{"file": "a.md"}], "dependencies": {"mode": "nope"}}
        )


def test_preprocessor_sandbox_follows_book_yml() -> None:
    env_book = Book.model_validate({"title": "T", "toc": [{"file": "a.md"}]})
    assert Preprocessor(env_book, book_dir=Path(".")).sandbox is False

    sbx_book = Book.model_validate(
        {"title": "T", "toc": [{"file": "a.md"}], "dependencies": {"mode": "sandbox"}}
    )
    assert Preprocessor(sbx_book, book_dir=Path(".")).sandbox is True


def test_preprocessor_sandbox_override_beats_book_yml() -> None:
    sbx_book = Book.model_validate(
        {"title": "T", "toc": [{"file": "a.md"}], "dependencies": {"mode": "sandbox"}}
    )
    # --no-sandbox forces off even though book.yml says sandbox
    assert Preprocessor(sbx_book, book_dir=Path("."), sandbox_override=False).sandbox is False
    # --sandbox forces on even though book.yml defaults to env
    env_book = Book.model_validate({"title": "T", "toc": [{"file": "a.md"}]})
    assert Preprocessor(env_book, book_dir=Path("."), sandbox_override=True).sandbox is True


def test_export_notebook_passes_sandbox_flag(tmp_path: Path) -> None:
    """``sandbox=True`` wraps the export runner in marimo's ``uv run --isolated``
    command (the runner replaced ``marimo export ipynb --sandbox``; see
    ``_export_command``)."""
    fake_py = tmp_path / "nb.py"
    fake_py.write_text("import marimo\napp = marimo.App()\n")

    # Mock subprocess.run to capture the cmd without actually invoking marimo.
    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    captured: list[list[str]] = []

    def fake_run(cmd, **_kw):
        if "--output" not in cmd:
            # marimo's construct_uv_flags shells out to `uv export` while
            # resolving requirements; that is not the export subprocess.
            return _FakeResult()
        captured.append(cmd)
        # Write a minimal valid .ipynb so export_notebook's JSON load succeeds.
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text('{"cells": [], "metadata": {}}')
        return _FakeResult()

    with patch.object(marimo_export.subprocess, "run", side_effect=fake_run):
        marimo_export.export_notebook(fake_py, sandbox=True)
        assert captured[-1][1] == "run" and "--isolated" in captured[-1]
        assert str(marimo_export._EXPORT_RUNNER) in captured[-1]

        marimo_export.export_notebook(fake_py, sandbox=False)
        assert "--isolated" not in captured[-1]
        assert captured[-1][1] == str(marimo_export._EXPORT_RUNNER)


def test_export_notebook_threads_suppress_warnings_env(tmp_path: Path) -> None:
    """``suppress_warnings=True`` sets PYTHONWARNINGS=ignore on the subprocess env."""
    fake_py = tmp_path / "nb.py"
    fake_py.write_text("import marimo\napp = marimo.App()\n")

    class _FakeResult:
        returncode = 0
        stdout = ""
        stderr = ""

    captured_envs: list[dict | None] = []

    def fake_run(cmd, **kw):
        captured_envs.append(kw.get("env"))
        out_path = Path(cmd[cmd.index("--output") + 1])
        out_path.write_text('{"cells": [], "metadata": {}}')
        return _FakeResult()

    with patch.object(marimo_export.subprocess, "run", side_effect=fake_run):
        marimo_export.export_notebook(fake_py, suppress_warnings=True)
        assert captured_envs[-1] is not None
        assert captured_envs[-1].get("PYTHONWARNINGS") == "ignore"

        marimo_export.export_notebook(fake_py, suppress_warnings=False)
        # Default — let subprocess inherit the parent environment unchanged.
        assert captured_envs[-1] is None
