"""Tests for ``mode: cached`` — committed ``_rendered/`` artifacts.

The point of the mode is that a fresh committed body is reused at build time
*without executing the notebook*. Tests patch the rendering functions so they
neither need a real ``marimo export`` nor (in the fresh-cache path) run at all.
"""

from __future__ import annotations

import shutil
from pathlib import Path
from unittest.mock import patch

from marimo_book.config import Book, FileEntry
from marimo_book.preprocessor import Preprocessor
from marimo_book.rendered_store import RenderedStore

FIXTURES = Path(__file__).parent / "fixtures"
NOTEBOOK_FIXTURE = FIXTURES / "simple_notebook.py"


def _book_with_cached_nb(book_dir: Path) -> Book:
    """A two-entry book: a markdown index + one cached notebook page."""
    content = book_dir / "content"
    content.mkdir(parents=True, exist_ok=True)
    (content / "intro.md").write_text("# Intro\n", encoding="utf-8")
    shutil.copy(NOTEBOOK_FIXTURE, content / "nb.py")
    return Book.model_validate(
        {
            "title": "T",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/nb.py", "mode": "cached"},
            ],
        }
    )


# --- config ----------------------------------------------------------------


def test_mode_cached_validates_at_default_and_entry_level() -> None:
    b = Book.model_validate(
        {"title": "T", "toc": [{"file": "a.md"}], "defaults": {"mode": "cached"}}
    )
    assert b.defaults.mode == "cached"
    e = FileEntry.model_validate({"file": "a.py", "mode": "cached"})
    assert e.effective_mode("static") == "cached"


# --- RenderedStore ----------------------------------------------------------


def test_store_write_then_fresh_roundtrip(tmp_path: Path) -> None:
    src = tmp_path / "content" / "nb.py"
    src.parent.mkdir(parents=True)
    src.write_text("print(1)\n")

    store = RenderedStore(tmp_path)
    store.write("content/nb.py", src, "BODY")
    store.save()

    reloaded = RenderedStore(tmp_path)
    assert reloaded.is_fresh("content/nb.py", src)
    assert reloaded.read_body("content/nb.py") == "BODY"
    # Committed tree mirrors the source path; manifest is committed alongside.
    assert (tmp_path / "_rendered" / "content" / "nb.md").exists()
    assert (tmp_path / "_rendered" / "manifest.json").exists()


def test_store_goes_stale_when_source_changes(tmp_path: Path) -> None:
    src = tmp_path / "nb.py"
    src.write_text("v1")
    store = RenderedStore(tmp_path)
    store.write("nb.py", src, "BODY")
    assert store.is_fresh("nb.py", src)

    src.write_text("v2-different-length")
    assert not store.is_fresh("nb.py", src)
    assert "changed" in store.reason_stale("nb.py", src)


def test_store_missing_entry_is_not_fresh(tmp_path: Path) -> None:
    src = tmp_path / "nb.py"
    src.write_text("x")
    store = RenderedStore(tmp_path)
    assert not store.is_fresh("nb.py", src)
    assert store.reason_stale("nb.py", src) == "no committed output"


# --- build: a fresh cached page must NOT execute ----------------------------


def test_build_cached_fresh_does_not_execute(tmp_path: Path) -> None:
    book = _book_with_cached_nb(tmp_path)
    src_abs = (tmp_path / "content" / "nb.py").resolve()
    pre = Preprocessor(book, book_dir=tmp_path)
    store = RenderedStore(tmp_path)
    store.write(
        "content/nb.py",
        src_abs,
        "# Cached Body\n\nHello from cache.\n",
        body_sig=pre.body_signature,
    )
    store.save()

    out_dir = tmp_path / "_site_src"
    # If anything tries to execute a notebook, this blows up the build.
    with patch(
        "marimo_book.preprocessor._render_marimo",
        side_effect=AssertionError("notebook executed in cached mode"),
    ):
        report = pre.build(out_dir=out_dir, site_dir=tmp_path / "_site")

    assert report.ok, report.errors
    # The notebook came from cache (no execution; the AssertionError side_effect
    # never fired, else report.ok would be False). pages_rendered == 1 is just
    # the markdown index, which always renders.
    assert report.pages_cached == 1
    assert report.pages_rendered == 1
    staged = out_dir / "docs" / "nb.md"
    assert staged.exists()
    assert "Hello from cache." in staged.read_text(encoding="utf-8")


def test_build_cached_stale_warns_and_falls_back_to_live(tmp_path: Path) -> None:
    book = _book_with_cached_nb(tmp_path)  # nothing committed → stale/missing
    pre = Preprocessor(book, book_dir=tmp_path)
    out_dir = tmp_path / "_site_src"
    with patch(
        "marimo_book.preprocessor._render_marimo",
        return_value="# Fresh\n\nrendered live.\n",
    ) as m:
        report = pre.build(out_dir=out_dir, site_dir=tmp_path / "_site")

    assert report.ok, report.errors
    # Both the markdown index and the fallback notebook render → 2.
    assert report.pages_rendered == 2
    assert report.pages_cached == 0
    assert any("mode=cached" in w for w in report.warnings)
    m.assert_called()  # the notebook fell back to a live render
    assert "rendered live." in (out_dir / "docs" / "nb.md").read_text(encoding="utf-8")


# --- `marimo-book render` (render_cached) -----------------------------------


def test_render_cached_writes_committed_store(tmp_path: Path) -> None:
    book = _book_with_cached_nb(tmp_path)
    pre = Preprocessor(book, book_dir=tmp_path)
    with patch(
        "marimo_book.preprocessor.render_py_body",
        return_value="# Committed\n\nbody.\n",
    ) as m:
        report = pre.render_cached()

    assert report.ok, report.errors
    assert report.pages_rendered == 1
    m.assert_called_once()
    store = RenderedStore(tmp_path)
    src_abs = (tmp_path / "content" / "nb.py").resolve()
    assert store.is_fresh("content/nb.py", src_abs)
    assert "body." in store.read_body("content/nb.py")


def test_render_cached_check_only_flags_then_passes(tmp_path: Path) -> None:
    book = _book_with_cached_nb(tmp_path)
    pre = Preprocessor(book, book_dir=tmp_path)

    # Nothing committed yet → check reports stale, writes nothing.
    report = pre.render_cached(check_only=True)
    assert report.pages == 1
    assert report.pages_rendered == 0
    assert report.warnings
    assert not (tmp_path / "_rendered").exists()

    # Commit, then check passes clean.
    with patch("marimo_book.preprocessor.render_py_body", return_value="# C\n"):
        pre.render_cached()
    report2 = pre.render_cached(check_only=True)
    assert not report2.warnings
    assert report2.pages_cached == 1


# --- freshness key: render-affecting config (not just source) ----------------


def test_store_goes_stale_when_body_sig_changes(tmp_path: Path) -> None:
    src = tmp_path / "nb.py"
    src.write_text("x")
    store = RenderedStore(tmp_path)
    store.write("nb.py", src, "BODY", body_sig="sig-A")

    # Same signature → fresh; different signature → stale, even though the
    # source bytes are identical.
    assert store.is_fresh("nb.py", src, body_sig="sig-A")
    assert not store.is_fresh("nb.py", src, body_sig="sig-B")
    assert "configuration" in store.reason_stale("nb.py", src, body_sig="sig-B")


def test_build_cached_stale_when_render_config_changes(tmp_path: Path) -> None:
    """A committed body must invalidate when render-affecting config changes."""
    book = _book_with_cached_nb(tmp_path)
    src_abs = (tmp_path / "content" / "nb.py").resolve()

    # Commit a body under the default config.
    pre1 = Preprocessor(book, book_dir=tmp_path)
    store = RenderedStore(tmp_path)
    store.write("content/nb.py", src_abs, "# Cached\n\nbody.\n", body_sig=pre1.body_signature)
    store.save()

    # Build with a DIFFERENT render-affecting config (toggle hide_first_code_cell).
    book2 = Book.model_validate(
        {
            "title": "T",
            "toc": [
                {"file": "content/intro.md"},
                {"file": "content/nb.py", "mode": "cached"},
            ],
            "defaults": {"hide_first_code_cell": False},
        }
    )
    pre2 = Preprocessor(book2, book_dir=tmp_path)
    assert pre2.body_signature != pre1.body_signature
    out_dir = tmp_path / "_site_src"
    with patch(
        "marimo_book.preprocessor._render_marimo",
        return_value="# Fresh\n\nre-rendered.\n",
    ) as m:
        report = pre2.build(out_dir=out_dir, site_dir=tmp_path / "_site")

    assert report.pages_cached == 0
    assert any("configuration" in w for w in report.warnings)
    m.assert_called()  # stale → fell back to a live render


# --- strict gate: a stale cached page must fail CI, not silently execute -----


def test_build_cached_stale_under_strict_errors_without_executing(tmp_path: Path) -> None:
    book = _book_with_cached_nb(tmp_path)  # nothing committed → stale/missing
    pre = Preprocessor(book, book_dir=tmp_path)
    out_dir = tmp_path / "_site_src"
    with patch(
        "marimo_book.preprocessor._render_marimo",
        side_effect=AssertionError("notebook executed under --strict cached build"),
    ):
        report = pre.build(out_dir=out_dir, site_dir=tmp_path / "_site", strict=True)

    assert not report.ok
    assert any("refusing to execute under --strict" in e for e in report.errors)
    assert report.pages_cached == 0
    assert report.pages_rendered == 1  # only the markdown index rendered
