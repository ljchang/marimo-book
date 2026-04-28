"""End-to-end tests for the Preprocessor's optional features."""

from __future__ import annotations

import json
import shutil
import time
from pathlib import Path
from unittest.mock import patch

import yaml

from marimo_book.config import Book, Dependencies
from marimo_book.preprocessor import Preprocessor, _maybe_stage_with_pep723
from marimo_book.transforms.pep723 import (
    has_pep723_block,
    read_existing_dependencies,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOTEBOOK_FIXTURE = FIXTURES / "simple_notebook.py"


def _minimal_book(book_dir: Path) -> None:
    """Lay down a minimal book at ``book_dir`` so Preprocessor.build runs."""
    (book_dir / "content").mkdir()
    (book_dir / "content" / "intro.md").write_text("# Intro\n\nHello.\n", encoding="utf-8")


def _book_config(*, include_changelog: bool) -> Book:
    return Book.model_validate(
        {
            "title": "Test",
            "include_changelog": include_changelog,
            "toc": [{"file": "content/intro.md"}],
        }
    )


def test_include_changelog_stages_file_and_appends_nav(tmp_path: Path) -> None:
    _minimal_book(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n## [0.1.0] — 2026-04-25\n\n- First release.\n",
        encoding="utf-8",
    )
    out_dir = tmp_path / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=True), book_dir=tmp_path)
    pre.build(out_dir=out_dir)

    staged = out_dir / "docs" / "changelog.md"
    assert staged.exists(), "include_changelog should copy CHANGELOG.md to docs/changelog.md"
    assert "First release." in staged.read_text(encoding="utf-8")

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    nav_titles = [list(e.keys())[0] if isinstance(e, dict) else e for e in mkdocs["nav"]]
    assert "Changelog" in nav_titles, f"nav should include Changelog entry; got {nav_titles}"


def test_include_changelog_off_by_default(tmp_path: Path) -> None:
    _minimal_book(tmp_path)
    (tmp_path / "CHANGELOG.md").write_text("# Changelog\n", encoding="utf-8")
    out_dir = tmp_path / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=False), book_dir=tmp_path)
    pre.build(out_dir=out_dir)

    assert not (out_dir / "docs" / "changelog.md").exists()
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    nav_titles = [list(e.keys())[0] if isinstance(e, dict) else e for e in mkdocs["nav"]]
    assert "Changelog" not in nav_titles


def test_include_changelog_finds_changelog_in_parent_dir(tmp_path: Path) -> None:
    """Common layout: book.yml in repo/docs/, CHANGELOG.md at repo root."""
    book_dir = tmp_path / "docs"
    book_dir.mkdir()
    _minimal_book(book_dir)
    (tmp_path / "CHANGELOG.md").write_text(
        "# Changelog\n\n- Found via parent fallback.\n", encoding="utf-8"
    )
    out_dir = book_dir / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=True), book_dir=book_dir)
    pre.build(out_dir=out_dir)

    staged = out_dir / "docs" / "changelog.md"
    assert staged.exists()
    assert "Found via parent fallback." in staged.read_text(encoding="utf-8")


def test_include_changelog_silent_when_no_file(tmp_path: Path) -> None:
    """Flag-on with no CHANGELOG.md is a no-op, not an error."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"

    pre = Preprocessor(_book_config(include_changelog=True), book_dir=tmp_path)
    report = pre.build(out_dir=out_dir)

    assert not (out_dir / "docs" / "changelog.md").exists()
    assert not report.errors


def test_first_toc_entry_promoted_to_index(tmp_path: Path) -> None:
    """The first TOC entry stages to docs/index.md so /index.html serves it.

    Without this, mkdocs's site root 404s and the header logo (which
    always links to /) takes the user nowhere.
    """
    content = tmp_path / "content"
    content.mkdir()
    (content / "intro.md").write_text("# Intro\n\nWelcome.\n", encoding="utf-8")
    (content / "next.md").write_text("# Next page\n", encoding="utf-8")
    book = Book.model_validate(
        {
            "title": "Test",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/next.md"},
            ],
        }
    )
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    # First entry promoted to index.md, original path NOT staged.
    assert (out_dir / "docs" / "index.md").exists()
    assert not (out_dir / "docs" / "intro.md").exists()
    # Subsequent entries unchanged.
    assert (out_dir / "docs" / "next.md").exists()
    # Nav references index.md, not intro.md.
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    assert "index.md" in mkdocs["nav"]
    assert "intro.md" not in mkdocs["nav"]


def test_empty_section_silently_skipped_in_nav(tmp_path: Path) -> None:
    """An empty section (no children) shouldn't crash and shouldn't render."""
    _minimal_book(tmp_path)
    book = Book.model_validate(
        {
            "title": "Test",
            "toc": [
                {"file": "content/intro.md"},
                # User stub with no children — common while drafting a TOC.
                {"section": "Coming soon", "children": None},
            ],
        }
    )
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    # Empty section should not appear in the nav.
    nav_labels = [next(iter(e.keys())) if isinstance(e, dict) else e for e in mkdocs["nav"]]
    assert "Coming soon" not in nav_labels


def test_logo_placement_sidebar_stages_stylesheet(tmp_path: Path) -> None:
    """`logo_placement: sidebar` should stage logo_sidebar.css and list it in extra_css."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"
    book = Book.model_validate(
        {
            "title": "Test",
            "logo_placement": "sidebar",
            "toc": [{"file": "content/intro.md"}],
        }
    )
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    assert (out_dir / "docs" / "stylesheets" / "logo_sidebar.css").exists()
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    # Asset URLs are versioned (?v=<marimo-book-version>) for cache busting.
    assert any(p.startswith("stylesheets/logo_sidebar.css") for p in mkdocs["extra_css"])


def test_logo_placement_header_omits_sidebar_stylesheet(tmp_path: Path) -> None:
    """Default header placement should not stage or reference logo_sidebar.css."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"
    book = Book.model_validate({"title": "Test", "toc": [{"file": "content/intro.md"}]})
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    assert not (out_dir / "docs" / "stylesheets" / "logo_sidebar.css").exists()
    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    assert not any(p.startswith("stylesheets/logo_sidebar.css") for p in mkdocs["extra_css"])


def test_pdf_export_adds_with_pdf_plugin(tmp_path: Path) -> None:
    """`pdf_export: true` should append `with-pdf` to the generated plugins."""
    _minimal_book(tmp_path)
    out_dir = tmp_path / "_site_src"
    book = Book.model_validate(
        {
            "title": "Test",
            "pdf_export": True,
            "toc": [{"file": "content/intro.md"}],
        }
    )

    pre = Preprocessor(book, book_dir=tmp_path)
    pre.build(out_dir=out_dir)

    mkdocs = yaml.safe_load((out_dir / "mkdocs.yml").read_text(encoding="utf-8"))
    plugin_names = [next(iter(p.keys())) if isinstance(p, dict) else p for p in mkdocs["plugins"]]
    assert "with-pdf" in plugin_names


# --- BuildCache --------------------------------------------------------------
#
# These tests drive the preprocessor end-to-end against a real .py notebook
# fixture, so they invoke `marimo export ipynb` per build. ~2-3 seconds each
# on a warm machine; we run a tiny notebook fixture to keep them fast.


def _book_with_notebook(book_dir: Path) -> Book:
    """Lay down a book with one Markdown page and one notebook (the fixture)."""
    content = book_dir / "content"
    content.mkdir(exist_ok=True)
    (content / "intro.md").write_text("# Intro\n", encoding="utf-8")
    shutil.copy(NOTEBOOK_FIXTURE, content / "notebook.py")
    return Book.model_validate(
        {
            "title": "Cache Test",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/notebook.py"},
            ],
        }
    )


def _manifest(out_dir: Path, book_dir: Path) -> dict:
    return json.loads(
        (book_dir / ".marimo_book_cache" / "manifest.json").read_text(encoding="utf-8")
    )


def test_cache_cold_then_warm(tmp_path: Path) -> None:
    """First build renders + writes manifest; second build hits the cache."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"

    cold = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert cold.pages_rendered == 2  # intro.md + notebook.py
    assert cold.pages_cached == 0
    assert (tmp_path / ".marimo_book_cache" / "manifest.json").exists()

    warm = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    # .md still re-renders (not cached); .py is the only cache target.
    assert warm.pages_cached == 1
    assert warm.pages_rendered == 1


def test_cache_invalidates_on_source_change(tmp_path: Path) -> None:
    """Editing the notebook source forces a re-render of just that entry."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"

    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    nb = tmp_path / "content" / "notebook.py"
    # Bump mtime AND content so both fast-path and slow-path miss.
    time.sleep(0.01)
    nb.write_text(nb.read_text(encoding="utf-8") + "\n# touched\n", encoding="utf-8")

    second = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_rendered == 2  # intro.md (always) + notebook.py (invalidated)
    assert second.pages_cached == 0


def test_rebuild_flag_forces_full_render(tmp_path: Path) -> None:
    """`rebuild=True` skips the cache even when entries are valid."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"

    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    forced = Preprocessor(book, book_dir=tmp_path, rebuild=True).build(out_dir=out_dir)
    assert forced.pages_cached == 0
    assert forced.pages_rendered == 2


def test_cache_invalidates_on_tool_version_change(tmp_path: Path) -> None:
    """Bumping the recorded marimo_book_version invalidates the whole cache."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    manifest_path = tmp_path / ".marimo_book_cache" / "manifest.json"
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    data["marimo_book_version"] = "0.0.0+impossible"
    manifest_path.write_text(json.dumps(data), encoding="utf-8")

    second = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_cached == 0
    assert second.pages_rendered == 2


def test_cache_invalidates_on_widget_defaults_change(tmp_path: Path) -> None:
    """Editing widget_defaults in book.yml invalidates rendered notebooks."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    book2 = Book.model_validate(
        {
            "title": "Cache Test",
            "widget_defaults": {"FakeWidget": {"x": 1}},
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/notebook.py"},
            ],
        }
    )
    second = Preprocessor(book2, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_cached == 0
    assert second.pages_rendered == 2


def test_cache_invalidates_when_staged_output_missing(tmp_path: Path) -> None:
    """If someone wipes _site_src but leaves the cache, we must re-render."""
    book = _book_with_notebook(tmp_path)
    out_dir = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)

    # Wipe the staged tree but leave the manifest alone.
    shutil.rmtree(out_dir)
    second = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert second.pages_cached == 0
    assert second.pages_rendered == 2


# --- PEP 723 staging --------------------------------------------------------


def test_maybe_stage_disabled_yields_none(tmp_path: Path) -> None:
    """``enabled=False`` is a fast no-op: no tempdir, no rewrite."""
    src = tmp_path / "nb.py"
    src.write_text("import numpy\n")
    with _maybe_stage_with_pep723(src, Dependencies(), enabled=False) as staged:
        assert staged is None


def test_maybe_stage_writes_block_to_sibling_tempdir(tmp_path: Path) -> None:
    """``enabled=True`` returns a sibling tempdir copy with PEP 723 injected.

    The sibling location matters: marimo's cell-execution cwd is the
    notebook's parent dir, so a copy under
    ``src.parent/marimo_book_pep723_*/<name>.py`` keeps cwd-based
    relative imports (``open("./data/foo.csv")``) resolving the same way
    as in the original notebook.
    """
    src = tmp_path / "nb.py"
    src.write_text("import marimo as mo\nimport numpy\nimport pandas\n")
    with _maybe_stage_with_pep723(src, Dependencies(), enabled=True) as staged:
        assert staged is not None
        assert staged.exists()
        # Sibling tempdir: parent of the staged file is a tempdir whose
        # parent is the original notebook's parent.
        assert staged.parent.parent == src.parent
        assert staged.parent.name.startswith("marimo_book_pep723_")
        rewritten = staged.read_text()
        assert has_pep723_block(rewritten)
        deps = read_existing_dependencies(rewritten)
        assert deps == ["numpy", "pandas"]
    # Tempdir cleaned up after context exit.
    assert not staged.parent.exists()


def test_maybe_stage_applies_extras_and_overrides(tmp_path: Path) -> None:
    """Extras and overrides round-trip through the staged file's block."""
    src = tmp_path / "nb.py"
    src.write_text("import nltools\nimport my_internal\n")
    deps_cfg = Dependencies(
        extras=["nltools>=0.5"],
        overrides={"my_internal": "my-internal-pkg"},
    )
    with _maybe_stage_with_pep723(src, deps_cfg, enabled=True) as staged:
        assert staged is not None
        deps = read_existing_dependencies(staged.read_text()) or []
    # Extras win for nltools (version specifier preserved); override wins for my_internal.
    assert "nltools>=0.5" in deps
    assert "my-internal-pkg" in deps


def test_stage_page_routes_wasm_through_staged_path(tmp_path: Path) -> None:
    """``stage_page`` for a WASM entry must call ``render_wasm_page`` with a
    staged source path whose contents include both the PEP 723 block AND
    the micropip bootstrap injected into the first ``@app.cell``.

    Verified by mocking ``render_wasm_page`` to capture the args before
    the tempdir is cleaned up.
    """
    from marimo_book.preprocessor import stage_page

    book_dir = tmp_path
    (book_dir / "content").mkdir()
    nb = book_dir / "content" / "nb.py"
    # Use the real fixture as the body so MarimoIslandGenerator never
    # actually runs (we mock the call). Adding `import numpy` so we have
    # something to install.
    nb.write_text(NOTEBOOK_FIXTURE.read_text(encoding="utf-8") + "\nimport numpy\n")
    docs_dir = tmp_path / "_site_src" / "docs"
    docs_dir.mkdir(parents=True)

    book = Book.model_validate(
        {
            "title": "T",
            "toc": [{"file": "content/nb.py", "mode": "wasm"}],
            "defaults": {"mode": "static"},
        }
    )
    captured: dict[str, str] = {}

    def fake_render(py_path, *, display_code=False, staged_source_path=None):
        # Capture the staged source content while the tempdir still exists.
        assert staged_source_path is not None, "WASM path must receive a staged source"
        captured["content"] = staged_source_path.read_text()
        return "<!-- mocked wasm body -->"

    with patch("marimo_book.preprocessor.render_wasm_page", side_effect=fake_render):
        stage_page(book, book_dir, book.toc[0], docs_dir)

    # PEP 723 block present and lists numpy.
    assert has_pep723_block(captured["content"])
    deps = read_existing_dependencies(captured["content"]) or []
    assert "numpy" in deps
    # WASM bootstrap injected: try/except + await micropip.install in the
    # first cell. Without this the islands runtime can't provision deps.
    assert "await micropip.install" in captured["content"]
    assert "except ImportError" in captured["content"]


def test_stage_page_auto_pep723_static_mode_skips_bootstrap(tmp_path: Path) -> None:
    """``auto_pep723: true`` for static pages writes the block but NOT the bootstrap.

    The bootstrap is WASM-specific (the islands runtime can't install
    deps any other way). Static pages run under a real Python env at
    build time and don't need a runtime micropip call.
    """
    from marimo_book.preprocessor import stage_page

    book_dir = tmp_path
    (book_dir / "content").mkdir()
    nb = book_dir / "content" / "nb.py"
    nb.write_text(NOTEBOOK_FIXTURE.read_text(encoding="utf-8") + "\nimport numpy\n")
    docs_dir = tmp_path / "_site_src" / "docs"
    docs_dir.mkdir(parents=True)

    book = Book.model_validate(
        {
            "title": "T",
            "toc": [{"file": "content/nb.py"}],  # default static
            "dependencies": {"auto_pep723": True},
        }
    )
    captured: dict[str, str] = {}

    def fake_render_marimo(src, book_arg, *, sandbox=False):
        # Read content while the staged tempdir is still alive (it gets
        # torn down on context exit, before the assertions below).
        captured["content"] = Path(src).read_text(encoding="utf-8")
        return "<!-- mocked -->"

    with patch("marimo_book.preprocessor._render_marimo", side_effect=fake_render_marimo):
        stage_page(book, book_dir, book.toc[0], docs_dir)

    staged_content = captured["content"]
    assert has_pep723_block(staged_content), "static auto_pep723 still emits the block"
    assert "await micropip.install" not in staged_content, (
        "static-mode pages must not get the WASM bootstrap"
    )


def test_stage_page_static_mode_skips_staging_by_default(tmp_path: Path) -> None:
    """Static-mode pages don't get PEP 723 staging unless ``auto_pep723: true``."""
    from marimo_book.preprocessor import stage_page

    book_dir = tmp_path
    (book_dir / "content").mkdir()
    nb = book_dir / "content" / "nb.py"
    nb.write_text(NOTEBOOK_FIXTURE.read_text(encoding="utf-8"))
    docs_dir = tmp_path / "_site_src" / "docs"
    docs_dir.mkdir(parents=True)

    book = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py"}]})
    captured = {"args": None}

    def fake_render(src, book_arg, *, sandbox=False):
        captured["args"] = src
        return "<!-- mocked -->"

    with patch("marimo_book.preprocessor._render_marimo", side_effect=fake_render):
        stage_page(book, book_dir, book.toc[0], docs_dir)

    # Default static path receives the ORIGINAL source, not a staged copy.
    assert captured["args"] == nb.resolve()
