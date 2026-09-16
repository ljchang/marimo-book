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


def test_stale_cached_page_warns_not_errors(tmp_path: Path) -> None:
    """Plain `build` warns and live-renders stale cached pages, so a
    non-strict `check` must not be harsher than the build it gates."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "mode": "cached"}]},
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)  # nothing committed → stale
    assert report.ok
    assert any("nb.py" in w and "marimo-book render" in w for w in report.warnings)


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
    assert not any("nb.py" in w for w in report.warnings)


# --- warnings -------------------------------------------------------------------


def test_missing_bib_file_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "bibliography": {"files": ["gone.bib"]},
            "toc": [{"file": "content/a.md"}],
        },
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("bibliography" in e and "gone.bib" in e for e in report.errors)


def test_unknown_citation_key_warns(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    (tmp_path / "refs.bib").write_text(
        "@book{doe2020, author={Doe, J.}, year={2020}, title={T}, publisher={P}}\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {
            "title": "T",
            "bibliography": {"files": ["refs.bib"]},
            "toc": [{"file": "content/a.md"}],
        },
        files=["content/a.md"],
    )
    (tmp_path / "content" / "a.md").write_text(
        "# A\nKnown [@doe2020], unknown [@typo2020], quoted `[@ok]`.\n", encoding="utf-8"
    )
    report = run_checks(book, tmp_path)
    assert any("[@typo2020]" in w for w in report.warnings)
    assert not any("doe2020" in w for w in report.warnings)
    assert not any("[@ok]" in w for w in report.warnings)  # code span exempt


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


def test_unparsable_bib_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    (tmp_path / "refs.bib").write_text("@article{broken", encoding="utf-8")
    book = _book(
        tmp_path,
        {"title": "T", "bibliography": {"files": ["refs.bib"]}, "toc": [{"file": "content/a.md"}]},
        files=["content/a.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("failed to parse" in e for e in report.errors)


def test_unknown_citation_key_warns_once_per_file(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    (tmp_path / "refs.bib").write_text(
        "@book{doe2020, author={Doe, J.}, year={2020}, title={T}, publisher={P}}\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {"title": "T", "bibliography": {"files": ["refs.bib"]}, "toc": [{"file": "content/a.md"}]},
        files=["content/a.md"],
    )
    (tmp_path / "content" / "a.md").write_text(
        "# A\nTwice [@typo2020] and again [@typo2020].\n", encoding="utf-8"
    )
    report = run_checks(book, tmp_path)
    assert sum("[@typo2020]" in w for w in report.warnings) == 1


def test_link_to_promoted_index_page_validates_by_staged_name(tmp_path: Path) -> None:
    """The first TOC entry stages as index.md; links must validate against
    staged names the way the build's rewriter resolves them."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/intro.md"}, {"file": "content/b.md"}]},
        files=["content/intro.md", "content/b.md"],
    )
    (tmp_path / "content" / "b.md").write_text("# B\n[home](index.md)\n", encoding="utf-8")
    report = run_checks(book, tmp_path)
    assert not any("index.md" in w for w in report.warnings)


# --- shell: zensical -----------------------------------------------------------


def test_zensical_shell_rejects_features_it_would_silently_drop(
    tmp_path: Path, monkeypatch
) -> None:
    """zensical ignores unsupported mkdocs plugins with 'No issues found',
    so `check` has to be the thing that refuses the combination."""
    from marimo_book import checks

    monkeypatch.setattr(checks, "_module_available", lambda name: True)
    (tmp_path / "blog").mkdir()
    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/a.md"}],
            "shell": "zensical",
            "social_cards": True,
            "blog": {"enabled": True},
            "check_external_links": True,
            "pdf_export": True,
        },
        files=["content/a.md"],
    )
    report = checks.run_checks(book, tmp_path)
    flagged = [e for e in report.errors if "shell: zensical" in e]
    assert len(flagged) == 4
    for label in ("social_cards", "blog.enabled", "check_external_links", "pdf_export"):
        assert any(e.startswith(f"{label}:") for e in flagged), label


def test_zensical_shell_with_supported_features_passes(tmp_path: Path, monkeypatch) -> None:
    from marimo_book import checks

    monkeypatch.setattr(checks, "_module_available", lambda name: True)
    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/a.md"}],
            "shell": "zensical",
            "cross_references": True,
            "include_changelog": True,
        },
        files=["content/a.md"],
    )
    report = checks.run_checks(book, tmp_path)
    assert report.ok, report.errors


def test_mkdocs_shell_never_triggers_zensical_errors(tmp_path: Path, monkeypatch) -> None:
    from marimo_book import checks

    monkeypatch.setattr(checks, "_module_available", lambda name: True)
    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/a.md"}], "social_cards": True},
        files=["content/a.md"],
    )
    report = checks.run_checks(book, tmp_path)
    assert not any("zensical" in e for e in report.errors)


def test_zensical_shell_needs_extra(tmp_path: Path, monkeypatch) -> None:
    from marimo_book import checks

    monkeypatch.setattr(checks, "_module_available", lambda name: name != "zensical")
    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/a.md"}], "shell": "zensical"},
        files=["content/a.md"],
    )
    report = checks.run_checks(book, tmp_path)
    assert any("[zensical]" in e for e in report.errors)


# --- workbench ------------------------------------------------------------------


def test_entry_open_in_outside_its_views_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/nb.py", "views": ["read", "run"], "open_in": "edit"}],
        },
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)
    assert any("open_in" in e and "content/nb.py" in e for e in report.errors)


def test_book_open_in_is_only_a_preference_for_narrower_pages(tmp_path: Path) -> None:
    """``defaults.open_in`` need not be offered by every page: a page that
    narrows its views falls back (effective_open_in), so no error."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "defaults": {"open_in": "edit", "views": ["read", "edit"]},
            "toc": [
                {"file": "content/nb.py", "views": ["run"], "open_in": "run"},
                {"file": "content/other.py", "views": ["read", "run"]},
            ],
        },
        files=["content/nb.py", "content/other.py"],
    )
    report = run_checks(book, tmp_path)
    assert not [e for e in report.errors if "open_in" in e]


def test_views_on_markdown_page_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/intro.md", "views": ["read", "edit"]}]},
        files=["content/intro.md"],
    )
    report = run_checks(book, tmp_path)
    assert any("only apply to marimo notebooks" in e for e in report.errors)


def test_native_dependency_on_workbench_page_warns(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}]},
        files=["content/nb.py"],
    )
    (tmp_path / "content" / "nb.py").write_text(
        "import marimo\napp = marimo.App()\n\n@app.cell\ndef _():\n    import torch\n    return\n",
        encoding="utf-8",
    )
    report = run_checks(book, tmp_path)
    assert any("torch" in w and "Pyodide" in w for w in report.warnings)
    assert not report.errors


def test_pyodide_wheel_list_excludes_installable_packages(tmp_path: Path) -> None:
    """nibabel/nilearn are pure Python (micropip installs them), Pyodide bundles
    lxml and opencv-python, and polars — Rust to the core — ships a wheel
    micropip installs and runs. None of them may warn; dartbrains has chapters
    importing all of them."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["nibabel", "nilearn", "lxml", "opencv-python", "polars"]},
            "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}],
        },
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)
    assert not [w for w in report.warnings if "Pyodide" in w]


def test_workbench_page_with_pure_deps_passes(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "run", "edit"]}]},
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)
    assert not report.errors
    assert not any("Pyodide" in w for w in report.warnings)


def test_native_dependency_with_any_specifier_warns(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["torch!=1.9", "numba~=0.60"]},
            "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}],
        },
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)
    warned = [w for w in report.warnings if "no Pyodide wheel" in w]
    assert len(warned) == 1 and "numba" in warned[0] and "torch" in warned[0]


def test_missing_assignment_file_is_error(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/nb.py", "assignment": "content/assignments/x.py"}],
        },
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)
    assert any("assignment references a missing file" in e for e in report.errors)


def test_assignment_without_pep723_block_warns(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/nb.py", "assignment": "content/assignments/x.py"}],
        },
        files=["content/nb.py", "content/assignments/x.py"],
    )
    report = run_checks(book, tmp_path)
    assert not report.errors
    assert any("no PEP 723 block" in w for w in report.warnings)


# --- a pin in the block does not survive the browser --------------------------


def test_pinned_workbench_dependencies_warn(tmp_path: Path) -> None:
    """marimo strips version specifiers before installing, so a pin is
    advisory in the browser. dartbrains pinned nltools==0.6.0.dev2 and readers
    got 0.5.1, which cannot run in Pyodide."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["nltools==0.6.0.dev2"]},
            "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}],
        },
        files=["content/nb.py"],
    )
    report = run_checks(book, tmp_path)
    warned = [w for w in report.warnings if "marimo drops version specifiers" in w]
    assert len(warned) == 1 and "nltools==0.6.0.dev2" in warned[0]


def test_an_unpinned_workbench_dependency_does_not_warn(tmp_path: Path) -> None:
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["nltools"]},
            "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}],
        },
        files=["content/nb.py"],
    )
    assert not [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]


def test_only_specifiers_that_can_change_the_version_are_flagged() -> None:
    """A dropped lower bound is almost always satisfied by whatever the bare
    name resolves to; warning about it would turn `check --strict` red for
    books that are fine. An exact pin, a compatible release or an upper bound
    can each exclude the version an unpinned install picks."""
    from marimo_book.checks import _is_pinned

    assert _is_pinned("nltools==0.6.0.dev2")
    assert _is_pinned("nltools===0.6.0")
    assert _is_pinned("nltools~=0.6")
    assert _is_pinned("nltools<0.7")
    assert _is_pinned("nltools>=0.5,<0.7")

    assert not _is_pinned("nltools>=0.6")
    assert not _is_pinned("nltools>0.6")
    assert _is_pinned("nltools!=0.5.1"), (
        "an exclusion is the opposite of a lower bound: dropping it installs "
        "precisely the version the author ruled out"
    )
    assert not _is_pinned("nltools")
    assert not _is_pinned("nltools @ https://example.invalid/nltools-0.6.0-py3-none-any.whl")
    assert not _is_pinned("not a requirement at all!!")


def test_a_read_only_page_may_pin_freely(tmp_path: Path) -> None:
    """The warning is about what the *browser* installs; a static page's
    dependencies are the build's business."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["nltools==0.6.0.dev2"]},
            "toc": [{"file": "content/nb.py"}],
        },
        files=["content/nb.py"],
    )
    assert not [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]


def test_a_pin_in_the_notebooks_own_block_is_flagged(tmp_path: Path) -> None:
    """`write_pep723_block(..., preserve_existing=True)` lets the notebook's own
    block win the merge, so a hand-written pin reaches the browser too — and
    used to slip past this check entirely."""
    from marimo_book.checks import run_checks

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text(
        '# /// script\n# dependencies = ["nltools==0.6.0.dev2"]\n# ///\n'
        "import marimo\n\napp = marimo.App()\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}]},
    )
    warned = [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]
    assert len(warned) == 1 and "nltools==0.6.0.dev2" in warned[0]


def test_pin_env_is_flagged_because_the_build_writes_pins(tmp_path: Path) -> None:
    """`pin: env` stamps `pkg==<installed>` into every staged workbench
    notebook — every one of which the browser reduces to a bare name."""
    from marimo_book.checks import run_checks

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text(
        "import marimo\n\napp = marimo.App()\n\n\n"
        "@app.cell\ndef _():\n    import yaml\n    return (yaml,)\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"pin": "env"},
            "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}],
        },
    )
    warned = [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]
    assert len(warned) == 1
    assert "pin: env has no effect on run/edit pages" in warned[0], (
        "listing every stamped requirement would inline the book's whole "
        "dependency set and give advice nobody can act on"
    )


def test_a_book_wide_pin_is_reported_once_not_per_page(tmp_path: Path) -> None:
    """`extras` are book-wide; one warning per page would be N copies of the
    same sentence, and `check --strict` exits nonzero on warnings."""
    from marimo_book.checks import run_checks

    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["nltools==0.6.0.dev2"]},
            "toc": [
                {"file": "content/a.py", "views": ["read", "edit"]},
                {"file": "content/b.py", "views": ["read", "edit"]},
                {"file": "content/c.py", "views": ["read", "edit"]},
            ],
        },
        files=["content/a.py", "content/b.py", "content/c.py"],
    )
    warned = [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]
    assert len(warned) == 1
    # Attributed per requirement: a book-wide extras pin lands on every page,
    # and a bare page count would not say which notebook carries what.
    assert "nltools==0.6.0.dev2 (content/a.py, content/b.py, content/c.py)" in warned[0]


def test_a_requirement_the_notebook_overrides_is_not_flagged(tmp_path: Path) -> None:
    """`preserve_existing=True` is a merge the notebook's own block wins by
    canonical name, so an extras pin whose name is already in the block never
    reaches the browser. Warning about it would turn `check --strict` red for a
    book that is fine."""
    from marimo_book.checks import run_checks

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text(
        '# /// script\n# dependencies = ["nltools"]\n# ///\nimport marimo\n\napp = marimo.App()\n',
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {
            "title": "T",
            "dependencies": {"extras": ["nltools==0.6.0.dev2"]},
            "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}],
        },
    )
    warned = [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]
    assert not warned, "the staged block carries bare `nltools`, so there is nothing to warn about"


def test_a_lower_bound_naming_a_prerelease_is_flagged() -> None:
    """The case this check exists for. Installers skip pre-releases unless a
    specifier asks for one, so `nltools>=0.6.0.dev2` resolves to the newest
    stable exactly as an exact pin does — and 0.5.1 cannot run in Pyodide."""
    from marimo_book.checks import _is_pinned

    assert _is_pinned("nltools>=0.6.0.dev2")
    assert _is_pinned("nltools>0.6.0rc1")
    assert not _is_pinned("nltools>=0.5.1"), "a stable lower bound is usually satisfied"
    assert not _is_pinned("nltools>=not-a-version")


def test_a_requirement_excluded_from_the_browser_is_not_flagged(tmp_path: Path) -> None:
    """marimo applies environment markers before installing, so a requirement
    that never reaches Pyodide must not fail `check --strict`."""
    from marimo_book.checks import _installed_in_browser, run_checks

    assert _installed_in_browser(['pywin32==306; sys_platform == "win32"']) == []
    assert _installed_in_browser(["nltools==0.6.0.dev2"]) == ["nltools==0.6.0.dev2"]

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text(
        "# /// script\n"
        '# dependencies = ["pywin32==306; sys_platform == \\"win32\\""]\n'
        "# ///\nimport marimo\n\napp = marimo.App()\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}]},
    )
    assert not [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]


def test_an_assignments_pin_is_flagged_even_on_a_read_only_page(tmp_path: Path) -> None:
    """An assignment is staged through the same `stage_workbench_notebook` call
    and booted in the drawer, so its block reaches the browser exactly as a
    chapter's does — and a chapter with `views: [read]` can still carry one."""
    from marimo_book.checks import run_checks

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text("import marimo\n\napp = marimo.App()\n", encoding="utf-8")
    (content / "hw.py").write_text(
        '# /// script\n# dependencies = ["nltools==0.6.0.dev2"]\n# ///\n'
        "import marimo\n\napp = marimo.App()\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {
            "title": "T",
            "toc": [{"file": "content/nb.py", "assignment": "content/hw.py"}],
        },
    )
    warned = [
        w for w in run_checks(book, tmp_path).warnings if "marimo drops version specifiers" in w
    ]
    assert len(warned) == 1
    assert "content/hw.py" in warned[0], "the assignment is what carries the pin"


def test_a_malformed_block_does_not_swallow_the_no_wheel_warning(tmp_path: Path) -> None:
    """The staged computation is its own try for this reason: an unrelated
    fault must not take the torch warning down with it."""
    from marimo_book.checks import run_checks

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text(
        '# /// script\n# dependencies = ["torch"\n# ///\n'  # unclosed bracket
        "import marimo\n\napp = marimo.App()\n\n\n"
        "@app.cell\ndef _():\n    import torch\n    return (torch,)\n",
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}]},
    )
    assert [w for w in run_checks(book, tmp_path).warnings if "no Pyodide wheel" in w]


def test_a_package_only_in_the_block_is_checked_for_a_wheel(tmp_path: Path) -> None:
    """A notebook can hand-list a package it never imports; the staged block
    carries it, micropip tries to install it, and `deps` would never see it."""
    from marimo_book.checks import run_checks

    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "nb.py").write_text(
        '# /// script\n# dependencies = ["torch"]\n# ///\nimport marimo\n\napp = marimo.App()\n',
        encoding="utf-8",
    )
    book = _book(
        tmp_path,
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "edit"]}]},
    )
    assert [w for w in run_checks(book, tmp_path).warnings if "no Pyodide wheel" in w]


def test_the_marker_filter_fallback_under_reports(monkeypatch) -> None:
    """If marimo moves the helper, keeping marker-guarded entries would turn
    `--strict` red with no hint the filter had vanished."""
    import builtins

    from marimo_book.checks import _installed_in_browser

    real = builtins.__import__

    def no_marimo(name, *args, **kwargs):
        if name.startswith("marimo._runtime"):
            raise ImportError("gone")
        return real(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", no_marimo)
    assert _installed_in_browser(['pywin32==306; sys_platform == "win32"']) == []
    assert _installed_in_browser(["nltools==0.6.0.dev2"]) == ["nltools==0.6.0.dev2"]
