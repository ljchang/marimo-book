"""Tests for `marimo-book check`'s build-free validations (checks.py)."""

from __future__ import annotations

from pathlib import Path

import yaml

from marimo_book.config import Book, load_book


def _book(tmp_path: Path, data: dict, *, files: list[str] | None = None) -> Book:
    """Write book.yml + the given content files, return the loaded Book."""
    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    for rel in files or []:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        if rel.endswith(".py"):
            p.write_text("import marimo\napp = marimo.App()\n", encoding="utf-8")
        else:
            p.write_text("# Page\n", encoding="utf-8")
    book_yml = tmp_path / "book.yml"
    book_yml.write_text(yaml.safe_dump(data), encoding="utf-8")
    return load_book(book_yml)


# --- errors -------------------------------------------------------------------


def test_missing_toc_file_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/a.md"}, {"file": "content/gone.py"}]},
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert not report.ok
    assert any("content/gone.py" in e and "missing" in e for e in report.errors)


def test_unsupported_suffix_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/notes.txt"}]},
        files=["content/notes.txt"],
    )
    report = run_checks(book, tmp_path)
    assert any("notes.txt" in e and "unsupported" in e.lower() for e in report.errors)


def test_missing_logo_and_favicon_are_errors(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "logo": "images/logo.png",
            "favicon": "images/favicon.ico",
            "toc": [{"file": "content/a.md"}],
        },
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("logo" in e for e in report.errors)
    assert any("favicon" in e for e in report.errors)


def test_missing_extra_is_error(tmp_path: Path, monkeypatch) -> None:
    from marimo_book import checks

    book = _book(
        tmp_path,
        {"title": "T", "social_cards": True, "toc": [{"file": "content/a.md"}]},
        files=["content/a.md"],
    )
    monkeypatch.setattr(checks, "_module_available", lambda name: False)
    report = checks.run_checks(book, tmp_path)
    assert any("social_cards" in e and "[social]" in e for e in report.errors)


def test_installed_extra_passes(tmp_path: Path, monkeypatch) -> None:
    from marimo_book import checks

    book = _book(
        tmp_path,
        {"title": "T", "social_cards": True, "toc": [{"file": "content/a.md"}]},
        files=["content/a.md"],
    )
    monkeypatch.setattr(checks, "_module_available", lambda name: True)
    report = checks.run_checks(book, tmp_path)
    assert not any("social_cards" in e for e in report.errors)


def test_stale_cached_page_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "mode": "cached"}]},
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)  # nothing committed → stale
    assert any("nb.py" in e and "marimo-book render" in e for e in report.errors)


def test_fresh_cached_page_passes(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks
    from marimo_book.preprocessor import _render_body_signature
    from marimo_book.rendered_store import RenderedStore

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "mode": "cached"}]},
        files=["content/nb.py"],
    )
    store = RenderedStore(tmp_path)
    store.write(
        "content/nb.py",
        tmp_path / "content" / "nb.py",
        "BODY",
        body_sig=_render_body_signature(book),
    )
    store.save()
    report = run_checks(book, tmp_path)
    assert not any("nb.py" in e for e in report.errors)


# --- warnings -------------------------------------------------------------------


def test_inert_bibliography_warns(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    (tmp_path / "refs.bib").write_text("@misc{k, title={T}}\n", encoding="utf-8")
    book = _book(
        tmp_path,
        {
            "title": "T",
            "bibliography": {"files": ["refs.bib"]},
            "toc": [{"file": "content/a.md"}],
        },
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("bibliography" in w and "not implemented" in w for w in report.warnings)


def test_reserved_launch_button_flags_warn(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "repo": "https://github.com/o/r",
            "launch_buttons": {"binder": True},
            "toc": [{"file": "content/a.md"}],
        },
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("launch_buttons.binder" in w for w in report.warnings)


def test_buttons_without_repo_warn(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path, {"title": "T", "toc": [{"file": "content/a.md"}]}, files=["content/a.md"]
    )
    report = run_checks(book, tmp_path)
    assert any("repo:" in w and "button row" in w for w in report.warnings)


def test_empty_section_warns(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/a.md"}, {"section": "Soon", "children": None}],
        },
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("'Soon'" in w for w in report.warnings)


def test_duplicate_staged_output_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    # intro.md occupies the first slot so neither colliding entry gets
    # promoted to index.md; x.py and x.md then both stage to x.md.
    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/x.md"},
                {"file": "content/x.py"},
            ],
        },
        files=["content/intro.md", "content/x.md", "content/x.py"],
    )
    report = run_checks(book, tmp_path)
    assert any("silently overwrite" in e for e in report.errors)


def test_broken_relative_link_warns_and_valid_ones_pass(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/a.md"}, {"file": "content/b.md"}]},
        files=["content/b.md"],
    )
    (tmp_path / "content" / "images").mkdir()
    (tmp_path / "content" / "images" / "fig.png").write_bytes(b"\x89PNG")
    (tmp_path / "content" / "a.md").write_text(
        "# A\n"
        "[ok page](b.md)\n"
        "[ok image](images/fig.png)\n"
        "[external](https://example.org)\n"
        "[anchor](#section)\n"
        "[broken](missing.md)\n"
        "[broken img](images/gone.png)\n",
        encoding="utf-8",
    )
    report = run_checks(book, tmp_path)
    broken = [w for w in report.warnings if "broken relative link" in w]
    assert len(broken) == 2
    assert any("missing.md" in w for w in broken)
    assert any("images/gone.png" in w for w in broken)


def test_links_in_code_fences_and_spans_are_ignored(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "include_changelog": True, "toc": [{"file": "content/a.md"}]},
        files=["content/a.md"],
    )
    (tmp_path / "content" / "a.md").write_text(
        "# A\n"
        "```markdown\n[example](not-a-real-page.md)\n```\n"
        "Use `[label](page.md)` syntax for cross-refs.\n"
        "[changelog](changelog.md)\n",  # generated page — valid with the flag on
        encoding="utf-8",
    )
    report = run_checks(book, tmp_path)
    assert not any("broken relative link" in w for w in report.warnings)
