"""Tests for the in-browser workbench (workbench.py + config + build wiring)."""

from __future__ import annotations

import hashlib
import shutil
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml
from pydantic import ValidationError

from marimo_book.config import Book, Defaults, FileEntry
from marimo_book.transforms.pep723 import has_pep723_block
from marimo_book.workbench import (
    WORKBENCH_DIR,
    frontend_config,
    marimo_static_dir,
    mount_page_html,
    render_workbench_block,
    stage_workbench_notebook,
    stage_workbench_runtime,
    workbench_enabled,
)

FIXTURES = Path(__file__).parent / "fixtures"
NOTEBOOK_FIXTURE = FIXTURES / "simple_notebook.py"


# --- config -------------------------------------------------------------------


def test_views_default_to_read_only() -> None:
    entry = FileEntry(file=Path("content/nb.py"))
    d = Defaults()
    assert entry.effective_views(d) == ["read"]
    assert entry.effective_open_in(d) == "read"
    assert not entry.uses_workbench(d)


def test_entry_views_override_defaults_and_pick_open_in() -> None:
    d = Defaults(views=["read", "edit"], open_in="edit")
    entry = FileEntry(file=Path("content/nb.py"))
    assert entry.effective_open_in(d) == "edit"
    entry = FileEntry(file=Path("content/nb.py"), views=["run", "edit"])
    # The book-wide open_in applies when this page offers that view …
    assert entry.effective_open_in(d) == "edit"
    assert entry.uses_workbench(d)
    # … and otherwise `read` (or the first listed view) wins.
    entry = FileEntry(file=Path("content/nb.py"), views=["run", "read"])
    assert entry.effective_open_in(d) == "read"
    entry = FileEntry(file=Path("content/nb.py"), views=["run"])
    assert entry.effective_open_in(d) == "run"
    entry = FileEntry(file=Path("content/nb.py"), views=["read", "run"], open_in="run")
    assert entry.effective_open_in(d) == "run"


def test_markdown_entries_never_use_the_workbench() -> None:
    d = Defaults(views=["read", "edit"])
    assert not FileEntry(file=Path("content/intro.md")).uses_workbench(d)


def test_defaults_open_in_must_be_listed() -> None:
    with pytest.raises(ValidationError, match="open_in"):
        Defaults(views=["read"], open_in="edit")


def test_views_must_be_nonempty_and_unique() -> None:
    with pytest.raises(ValidationError, match="at least one"):
        Defaults(views=[])
    with pytest.raises(ValidationError, match="repeats"):
        FileEntry(file=Path("a.py"), views=["read", "read"])
    with pytest.raises(ValidationError):
        FileEntry(file=Path("a.py"), views=["view"])


def test_workbench_enabled_needs_a_run_or_edit_notebook() -> None:
    book = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py"}]})
    assert not workbench_enabled(book)
    book = Book.model_validate(
        {"title": "T", "toc": [{"file": "content/nb.py", "views": ["read", "run"]}]}
    )
    assert workbench_enabled(book)
    book = Book.model_validate(
        {
            "title": "T",
            "defaults": {"views": ["read", "edit"]},
            "toc": [{"file": "content/intro.md"}],
        }
    )
    assert not workbench_enabled(book)  # only .md pages: nothing to mount


# --- mount page ---------------------------------------------------------------


def test_mount_page_swaps_marimos_frozen_config_for_our_script() -> None:
    index = (marimo_static_dir() / "index.html").read_text(encoding="utf-8")
    html = mount_page_html(index, marimo_version="9.9.9", config={"save": {"autosave": "off"}})
    assert "__MARIMO_MOUNT_CONFIG__" not in html.split("<body>")[1].split("wb-mount.js")[0]
    assert 'src="./wb-mount.js"' in html and 'src="./wb-store.js"' in html
    assert '"marimoVersion": "9.9.9"' in html
    assert "<marimo-wasm hidden" in html
    assert "{{ " not in html, "every template placeholder must be filled"
    # marimo's own bundle keeps loading from ./assets/ next to the page.
    assert 'src="./assets/' in html


def test_mount_page_rejects_an_unknown_index_layout() -> None:
    with pytest.raises(RuntimeError, match="__MARIMO_MOUNT_CONFIG__"):
        mount_page_html("<html><head></head><body></body></html>", marimo_version="1", config={})


def test_frontend_config_pins_the_knobs_persistence_relies_on() -> None:
    cfg = frontend_config()
    assert cfg["save"]["autosave"] == "after_delay"
    assert cfg["runtime"]["auto_instantiate"] is True
    assert cfg["completion"]["copilot"] is False
    assert cfg["language_servers"]["pylsp"]["enabled"] is False


# --- runtime staging ----------------------------------------------------------


def _fake_static(tmp_path: Path) -> Path:
    """A stand-in for marimo/_static: real index.html, tiny assets."""
    static = tmp_path / "static"
    (static / "assets").mkdir(parents=True)
    shutil.copy(marimo_static_dir() / "index.html", static / "index.html")
    (static / "assets" / "index-abc.js").write_text("// bundle\n")
    return static


def test_stage_runtime_copies_assets_once_per_marimo_version(tmp_path: Path) -> None:
    static = _fake_static(tmp_path)
    docs = tmp_path / "docs"
    wb = stage_workbench_runtime(docs, static_dir=static, marimo_version="1.0.0")
    assert wb == docs / WORKBENCH_DIR
    assert (wb / "assets" / "index-abc.js").exists()
    assert (wb / "index.html").exists()
    assert (wb / "wb-store.js").exists() and (wb / "wb-mount.js").exists()

    # Same version: the assets copy is left alone (a stray file survives).
    (wb / "assets" / "stray").write_text("x")
    stage_workbench_runtime(docs, static_dir=static, marimo_version="1.0.0")
    assert (wb / "assets" / "stray").exists()

    # New marimo version: assets are replaced wholesale.
    stage_workbench_runtime(docs, static_dir=static, marimo_version="1.1.0")
    assert not (wb / "assets" / "stray").exists()
    assert (wb / ".marimo-version").read_text().strip() == "1.1.0"


def test_stage_notebook_writes_pep723_copy_and_hashes_those_bytes(tmp_path: Path) -> None:
    src = tmp_path / "content" / "nb.py"
    src.parent.mkdir()
    src.write_text(NOTEBOOK_FIXTURE.read_text() + "\nimport numpy\n")
    docs = tmp_path / "docs"
    book = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py"}]})
    url, digest = stage_workbench_notebook(
        src, Path("content/nb.py"), docs, book.dependencies, requires_python=">=3.11"
    )
    assert url == "_workbench/nb/content/nb.py"
    staged = (docs / url).read_text(encoding="utf-8")
    assert has_pep723_block(staged)
    assert "numpy" in staged.split("# ///")[1]
    assert digest == hashlib.sha256(staged.encode("utf-8")).hexdigest()
    # The source itself is never touched.
    assert not has_pep723_block(src.read_text())


# --- page block ---------------------------------------------------------------


def _block(entry_kwargs: dict, rel: str, **book_kwargs) -> str:
    book = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py"}], **book_kwargs})
    entry = FileEntry(file=Path("content/nb.py"), **entry_kwargs)
    return render_workbench_block(
        entry=entry,
        book=book,
        nb_url="_workbench/nb/content/nb.py",
        published_hash="abc123",
        rel_under_docs=Path(rel),
    )


def test_block_carries_page_data_relative_to_the_page() -> None:
    html = _block({"views": ["read", "edit"]}, "nb.md")
    assert 'data-src="../_workbench/nb/content/nb.py"' in html
    assert 'data-wb-root="../_workbench/"' in html
    assert 'data-hash="abc123"' in html
    assert 'data-views="read,edit"' in html
    assert 'data-open-in="read"' in html
    assert 'data-checkpoint-minutes="10"' in html and 'data-max-checkpoints="20"' in html
    # Only the listed views get a button; the default one is pressed.
    assert 'data-view="read" aria-pressed="true"' in html
    assert 'data-view="edit" aria-pressed="false"' in html
    assert 'data-view="run"' not in html
    assert "\n\n" not in html, "one raw HTML block for Python-Markdown"


def test_block_depth_and_open_in_follow_the_page() -> None:
    html = _block({"views": ["run", "edit"], "open_in": "edit"}, "index.md")
    assert 'data-src="_workbench/nb/content/nb.py"' in html  # home page: no ../
    assert 'data-view="edit" aria-pressed="true"' in html
    html = _block({"views": ["read", "run"]}, "a/b/nb.md", workbench={"checkpoint_minutes": 3})
    assert 'data-wb-root="../../../_workbench/"' in html
    assert 'data-checkpoint-minutes="3"' in html


# --- build wiring ---------------------------------------------------------------


def _book_dir(tmp_path: Path, entry: dict) -> Path:
    content = tmp_path / "content"
    content.mkdir(exist_ok=True)
    (content / "intro.md").write_text("# Intro\n", encoding="utf-8")
    shutil.copy(NOTEBOOK_FIXTURE, content / "nb.py")
    (tmp_path / "book.yml").write_text(
        yaml.safe_dump({"title": "T", "toc": [{"file": "content/intro.md"}, entry]}),
        encoding="utf-8",
    )
    return tmp_path


def test_build_stages_runtime_notebook_and_block_for_workbench_pages(tmp_path: Path) -> None:
    from marimo_book.config import load_book
    from marimo_book.preprocessor import Preprocessor

    book_dir = _book_dir(tmp_path, {"file": "content/nb.py", "views": ["read", "edit"]})
    book = load_book(book_dir / "book.yml")
    out = tmp_path / "_site_src"
    with patch("marimo_book.workbench.marimo_static_dir", return_value=_fake_static(tmp_path)):
        Preprocessor(book, book_dir=book_dir).build(out_dir=out)

    docs = out / "docs"
    assert (docs / WORKBENCH_DIR / "index.html").exists()
    assert (docs / WORKBENCH_DIR / "assets" / "index-abc.js").exists()
    assert (docs / WORKBENCH_DIR / "nb" / "content" / "nb.py").exists()
    assert (docs / "javascripts" / "workbench.js").exists()
    assert (docs / "javascripts" / "wb-store.js").exists()
    assert (docs / "stylesheets" / "workbench.css").exists()
    page = (docs / "nb.md").read_text(encoding="utf-8")
    assert 'id="wb-toolbar"' in page and 'data-views="read,edit"' in page
    assert page.index("wb-block") < page.index("Simple Notebook")
    cfg = yaml.safe_load((out / "mkdocs.yml").read_text())
    assert any("workbench.css" in c for c in cfg["extra_css"])
    js = [j["path"] for j in cfg["extra_javascript"] if isinstance(j, dict)]
    store = next(i for i, p in enumerate(js) if "wb-store.js" in p)
    shell = next(i for i, p in enumerate(js) if "workbench.js" in p)
    assert store < shell, "the store must load before the shell"
    # The Markdown page gets no block.
    assert "wb-toolbar" not in (docs / "index.md").read_text(encoding="utf-8")


def test_build_ships_nothing_for_read_only_books(tmp_path: Path) -> None:
    from marimo_book.config import load_book
    from marimo_book.preprocessor import Preprocessor

    book_dir = _book_dir(tmp_path, {"file": "content/nb.py"})
    book = load_book(book_dir / "book.yml")
    out = tmp_path / "_site_src"
    Preprocessor(book, book_dir=book_dir).build(out_dir=out)
    docs = out / "docs"
    assert not (docs / WORKBENCH_DIR).exists()
    assert not (docs / "javascripts" / "workbench.js").exists()
    assert "wb-toolbar" not in (docs / "nb.md").read_text(encoding="utf-8")
    cfg = yaml.safe_load((out / "mkdocs.yml").read_text())
    assert not any("workbench" in c for c in cfg["extra_css"])
