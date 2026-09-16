"""Tests for the in-browser workbench (workbench.py + config + build wiring)."""

from __future__ import annotations

import hashlib
import re
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
    assert 'src="./wb-mount.js?v=' in html and 'src="./wb-store.js?v=' in html
    assert '"marimoVersion": "9.9.9"' in html
    assert "<marimo-wasm hidden" in html
    assert "{{ " not in html, "every template placeholder must be filled"
    # marimo's own bundle still comes from ./assets/ next to the page — but by
    # way of __WB__.bundle now, so wb-mount.js can start it once the mount
    # config carries the notebook rather than letting it race the read.
    assert '"bundle": "./assets/' in html
    assert '<script type="module"' not in html


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


# --- cache signature --------------------------------------------------------------


def test_views_never_invalidate_cached_renders() -> None:
    """``views`` / ``open_in`` are finalize-time chrome: toggling them book-wide
    must not change the render-body signature (which would mark every committed
    ``_rendered/`` body stale and force a full re-execution)."""
    from marimo_book.preprocessor import _render_body_signature

    plain = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py"}]})
    edited = Book.model_validate(
        {
            "title": "T",
            "toc": [{"file": "content/nb.py"}],
            "defaults": {"views": ["read", "run", "edit"], "open_in": "edit"},
        }
    )
    assert _render_body_signature(plain) == _render_body_signature(edited)


# --- precompute splice ------------------------------------------------------------


def test_precompute_splice_keeps_the_workbench_block_and_tail() -> None:
    """The splice rebuilds ``buttons + body``; the workbench block (which nests
    divs, so the buttons' first-close trick can't find its end) and any tail
    after the body must survive, or a precomputed page loses Read/Run/Edit."""
    from types import SimpleNamespace

    from marimo_book.preprocessor import _spliced_page_and_body
    from marimo_book.workbench import WORKBENCH_BLOCK_END, WORKBENCH_TAIL_START

    block = _block({"views": ["read", "edit"]}, "nb.md")
    assert block.endswith(WORKBENCH_BLOCK_END)
    original = (
        '<div class="marimo-book-buttons" data-placement="header"><a>x</a></div>\n\n'
        + block
        + "\n\n<p>old body</p>\n\n"
        + WORKBENCH_TAIL_START
        + '\n<section id="wb-assignment">card</section>\n'
    )
    result = SimpleNamespace(body="<p>new body</p>", widget_html="", splice_anchor_cell_idx=None)
    page, body = _spliced_page_and_body(original, result)
    assert body == "<p>new body</p>"
    assert page.index("marimo-book-buttons") < page.index("wb-toolbar") < page.index("new body")
    assert "old body" not in page
    assert page.rstrip().endswith('<section id="wb-assignment">card</section>')


# --- assignments ------------------------------------------------------------------

ASSIGNMENT_SRC = '''# /// script
# dependencies = ["marimo", "marimo-grader-client"]
# grader-server = "https://grader.example.edu"
# grader-assignment = "pandas"
# grader-version = "3"
# ///

import marimo

app = marimo.App()


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
        # Assignment: Introduction to Pandas

        Read the chapter first.

        ## Q1. Load the data
        ## Q2. Group and aggregate
        """
    )
    return


if __name__ == "__main__":
    app.run()
'''


def test_read_assignment_info_from_the_notebook() -> None:
    from marimo_book.workbench import read_assignment_info

    info = read_assignment_info(
        ASSIGNMENT_SRC, file=Path("content/assignments/pandas.py"), nb_url="u", published_hash="h"
    )
    assert info.title == "Introduction to Pandas"  # "Assignment:" prefix stripped
    assert info.grader_server == "https://grader.example.edu"
    assert info.grader_assignment == "pandas" and info.grader_version == "3"
    assert info.questions == ("Q1. Load the data", "Q2. Group and aggregate")


def test_read_assignment_info_ignores_python_comments() -> None:
    """Only ``mo.md`` prose counts: an indented ``# comment`` in a code cell
    ahead of the intro is not the title, nor is a commented-out ``## call``."""
    from marimo_book.workbench import read_assignment_info

    src = (
        "import marimo\n\napp = marimo.App()\n\n\n"
        "@app.cell\ndef _():\n    # Import libraries\n    import marimo as mo\n"
        "    ## old_call(mo)\n    return (mo,)\n\n\n"
        '@app.cell\ndef _(mo):\n    mo.md(\n        r"""\n        # Real title\n\n'
        '        ## Q1. Real question\n        """\n    )\n    return\n'
    )
    info = read_assignment_info(src, file=Path("a.py"), nb_url="u", published_hash="h")
    assert info.title == "Real title"
    assert info.questions == ("Q1. Real question",)


def test_read_assignment_info_degrades_without_a_header() -> None:
    from marimo_book.workbench import read_assignment_info

    info = read_assignment_info(
        "import marimo\napp = marimo.App()\n",
        file=Path("content/assignments/week_one.py"),
        nb_url="u",
        published_hash="h",
    )
    assert info.title == "week one"
    assert info.grader_server == "" and info.questions == ()


def test_assignment_tail_carries_card_and_drawer() -> None:
    from marimo_book.workbench import read_assignment_info, render_assignment_tail

    info = read_assignment_info(
        ASSIGNMENT_SRC,
        file=Path("content/assignments/pandas.py"),
        nb_url="_workbench/nb/content/assignments/pandas.py",
        published_hash="abc",
    )
    html = render_assignment_tail(info, rel_under_docs=Path("a/nb.md"))
    assert 'id="wb-assignment"' in html and 'id="wb-drawer"' in html
    assert 'data-src="../../_workbench/nb/content/assignments/pandas.py"' in html
    assert 'data-grader-server="https://grader.example.edu"' in html
    assert "<li>Q1. Load the data</li>" in html
    assert "Assignment: Introduction to Pandas" in html
    assert "pandas · v3" in html
    assert "\n\n" not in html, "one raw HTML block for Python-Markdown"


def test_assignment_tail_without_questions_stays_one_html_block() -> None:
    from marimo_book.workbench import read_assignment_info, render_assignment_tail

    info = read_assignment_info(
        "import marimo\napp = marimo.App()\n", file=Path("hw.py"), nb_url="u", published_hash="h"
    )
    html = render_assignment_tail(info, rel_under_docs=Path("nb.md"))
    assert "wb-questions" not in html
    assert "\n\n" not in html, "one raw HTML block for Python-Markdown"


def test_assignment_only_page_ships_the_shell_without_a_chapter_copy(tmp_path: Path) -> None:
    from marimo_book.config import load_book
    from marimo_book.preprocessor import Preprocessor

    book_dir = _book_dir(
        tmp_path, {"file": "content/nb.py", "assignment": "content/assignments/hw.py"}
    )
    (book_dir / "content" / "assignments").mkdir()
    (book_dir / "content" / "assignments" / "hw.py").write_text(ASSIGNMENT_SRC, encoding="utf-8")
    book = load_book(book_dir / "book.yml")
    out = tmp_path / "_site_src"
    with patch("marimo_book.workbench.marimo_static_dir", return_value=_fake_static(tmp_path)):
        Preprocessor(book, book_dir=book_dir).build(out_dir=out)

    docs = out / "docs"
    assert (docs / WORKBENCH_DIR / "index.html").exists()
    assert (docs / WORKBENCH_DIR / "nb" / "content" / "assignments" / "hw.py").exists()
    assert not (docs / WORKBENCH_DIR / "nb" / "content" / "nb.py").exists()  # views: [read]
    page = (docs / "nb.md").read_text(encoding="utf-8")
    assert 'data-views="read"' in page and 'data-src=""' in page
    assert page.index("wb-block") < page.index("Simple Notebook") < page.index('id="wb-assignment"')
    assert page.rstrip().endswith("</div>")  # the drawer closes the page
    from marimo_book.workbench import WORKBENCH_TAIL_START

    assert (
        page.index("Simple Notebook")
        < page.index(WORKBENCH_TAIL_START)
        < page.index("wb-assignment")
    )
    assert 'id="wb-asg-update"' in page
    from marimo_book.workbench import WORKBENCH_TAIL_START

    assert (
        page.index("Simple Notebook")
        < page.index(WORKBENCH_TAIL_START)
        < page.index("wb-assignment")
    )


def test_assignment_key_validates() -> None:
    book = Book.model_validate(
        {"title": "T", "toc": [{"file": "content/nb.py", "assignment": "content/assignments/a.py"}]}
    )
    assert book.toc[0].assignment == Path("content/assignments/a.py")
    assert book.toc[0].uses_shell(book.defaults) and not book.toc[0].uses_workbench(book.defaults)
    assert workbench_enabled(book)


# --- the reader must not be asked to install packages by hand -----------------


def test_the_mount_page_holds_marimos_bundle_back() -> None:
    """marimo's frontend is a module script, so it runs after parsing — before
    an awaited IndexedDB read could fill in `code`. wb-mount.js appends it once
    the config carries the notebook."""
    import marimo

    from marimo_book.workbench import mount_page_html

    index = (Path(marimo.__file__).parent / "_static" / "index.html").read_text()
    out = mount_page_html(index, marimo_version="0.24.2", config={})

    assert '<script type="module"' not in out, "the bundle must not auto-run"
    assert '"bundle"' in out, "its URL has to reach wb-mount.js"
    assert "wb-mount.js" in out
    assert "<marimo-wasm" in out


def test_a_newer_marimo_without_a_bundle_script_is_an_error() -> None:
    """Silently shipping a page that never boots would be worse."""
    import pytest

    from marimo_book.workbench import mount_page_html

    stub = (
        '<html><head><script data-marimo="true">'
        'Object.defineProperty(window, "__MARIMO_MOUNT_CONFIG__", {})</script>'
        "</head></html>"
    )
    with pytest.raises(RuntimeError, match="module bundle script"):
        mount_page_html(stub, marimo_version="0.24.2", config={})


def test_the_mount_script_reads_the_notebook_before_configuring() -> None:
    source = (
        Path(__file__).parent.parent
        / "src"
        / "marimo_book"
        / "assets"
        / "workbench"
        / "wb-mount.js"
    ).read_text()

    assert 'code: ""' not in source, "an empty code hides the notebook's PEP 723 block"
    assert ".readFile()" in source
    assert "__WB__" in source


def test_the_workbench_scripts_are_version_stamped() -> None:
    """The mount page and these scripts are a matched pair now. Unstamped, a
    browser could serve one from cache and the other from the network across an
    upgrade — a page whose bundle is stripped but whose script never injects it
    never boots at all."""
    import marimo

    from marimo_book.workbench import mount_page_html

    index = (Path(marimo.__file__).parent / "_static" / "index.html").read_text()
    a = mount_page_html(index, marimo_version="1.0.0", config={})
    b = mount_page_html(index, marimo_version="2.0.0", config={})

    stamp = re.compile(r'wb-mount\.js\?v=([^"]+)')
    assert stamp.search(a) and stamp.search(b)
    assert stamp.search(a).group(1) != stamp.search(b).group(1), (
        "a marimo upgrade must produce new script URLs"
    )


def test_the_entry_bundle_is_preloaded_after_being_held_back() -> None:
    """Removing the script also removed the only thing fetching the entry
    chunk — marimo preloads every *other* chunk but not that one — so Pyodide's
    boot would no longer overlap the notebook read."""
    import marimo

    from marimo_book.workbench import mount_page_html

    index = (Path(marimo.__file__).parent / "_static" / "index.html").read_text()
    html = mount_page_html(index, marimo_version="0.24.2", config={})

    src = re.search(r'"bundle": "([^"]+)"', html).group(1)
    assert f'<link rel="modulepreload" crossorigin href="{src}">' in html


def test_a_mount_page_without_a_held_back_bundle_still_configures_marimo() -> None:
    """A page cached from an older marimo-book still has marimo's module script
    inline, and it runs at the end of parsing — before any awaited read could
    resolve. The script must publish a config synchronously there rather than
    leave marimo reading `undefined`."""
    source = (
        Path(__file__).parent.parent
        / "src"
        / "marimo_book"
        / "assets"
        / "workbench"
        / "wb-mount.js"
    ).read_text()

    assert "if (!boot.bundle) {" in source
    head, _, tail = source.partition("if (!boot.bundle) {")
    legacy = tail.split("} else {")[0]
    assert "__MARIMO_MOUNT_CONFIG__ = mountConfig(" in legacy
    assert "readFile" not in legacy, "the legacy path must not await anything"
