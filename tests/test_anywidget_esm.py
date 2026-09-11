"""anywidget ES-module delivery on marimo >= 0.24 (issue #79).

marimo 0.24 stopped putting a widget's ES module on the ``<marimo-anywidget>``
element (``data-js-url``); it travels on the kernel's model notifications.
These tests run a *real* notebook that defines an inline anywidget through
both build paths and assert the mount the page ships can still load the
module — the fixture-based tests elsewhere can't catch this class of
regression.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor
from marimo_book.transforms.anywidgets import rewrite_anywidget_html
from marimo_book.transforms.marimo_export import (
    _EXPORT_RUNNER,
    _export_command,
    cells_to_markdown,
    export_notebook,
)

pytest.importorskip("anywidget")

_WIDGET_NB = """import marimo

app = marimo.App()


@app.cell
def _():
    import marimo as mo
    import anywidget
    import traitlets

    class Hello(anywidget.AnyWidget):
        _esm = "export default { render({ model, el }) { el.textContent = 'hello ' + model.get('who'); } }"
        who = traitlets.Unicode("world").tag(sync=True)

    w = mo.ui.anywidget(Hello())
    w
    return


if __name__ == "__main__":
    app.run()
"""


def _write_nb(tmp_path: Path) -> Path:
    nb = tmp_path / "content" / "nb.py"
    nb.parent.mkdir(parents=True, exist_ok=True)
    nb.write_text(_WIDGET_NB, encoding="utf-8")
    return nb


# --- unit: rewrite restores data-js-url from the map -------------------------


def test_rewrite_restores_js_url_from_model_map() -> None:
    html = (
        "<marimo-anywidget data-initial-value='{\"who\": \"x\"}' data-label='null' "
        "data-model-id='\"abc123\"'></marimo-anywidget>"
    )
    out = rewrite_anywidget_html(html, esm_by_model={"abc123": "data:text/javascript;base64,Zm9v"})
    assert 'class="marimo-book-anywidget"' in out
    assert "data-js-url" in out and "Zm9v" in out


def test_rewrite_keeps_existing_js_url_and_ignores_unknown_model() -> None:
    html = (
        "<marimo-anywidget data-js-url='\"data:text/javascript;base64,T0xE\"' "
        "data-model-id='\"abc\"'></marimo-anywidget>"
        "<marimo-anywidget data-model-id='\"zzz\"'></marimo-anywidget>"
    )
    out = rewrite_anywidget_html(html, esm_by_model={"abc": "data:text/javascript;base64,TkVX"})
    assert "T0xE" in out and "TkVX" not in out  # pre-0.24 attribute wins
    assert out.count("data-js-url") == 1  # unknown model: no attribute invented


# --- runner shape -------------------------------------------------------------


def test_export_command_uses_runner_and_sandbox_wraps_with_uv(tmp_path: Path) -> None:
    nb = _write_nb(tmp_path)
    cmd, cleanup = _export_command(
        nb, tmp_path / "o.ipynb", tmp_path / "m.json", include_outputs=True, sandbox=False
    )
    cleanup()
    assert cmd[1] == str(_EXPORT_RUNNER) and "--models" in cmd
    assert _EXPORT_RUNNER.is_file()

    if shutil.which("uv") is None:
        with pytest.raises(RuntimeError, match="needs `uv`"):
            _export_command(
                nb, tmp_path / "o.ipynb", tmp_path / "m.json", include_outputs=True, sandbox=True
            )
        return
    cmd, cleanup = _export_command(
        nb, tmp_path / "o.ipynb", tmp_path / "m.json", include_outputs=True, sandbox=True
    )
    try:
        assert cmd[1] == "run" and "--isolated" in cmd
        assert "python" in cmd and str(_EXPORT_RUNNER) in cmd
        req = cmd[cmd.index("--with-requirements") + 1]
        assert Path(req).is_file() and "marimo" in Path(req).read_text()
    finally:
        cleanup()
    assert not Path(req).exists()

    # Without outputs there is nothing to harvest: plain marimo export,
    # which still honours sandbox via marimo's own flag.
    cmd, cleanup = _export_command(
        nb, tmp_path / "o.ipynb", tmp_path / "m.json", include_outputs=False, sandbox=False
    )
    cleanup()
    assert cmd[1:5] == ["-m", "marimo", "export", "ipynb"] and "--sandbox" not in cmd
    cmd, cleanup = _export_command(
        nb, tmp_path / "o.ipynb", tmp_path / "m.json", include_outputs=False, sandbox=True
    )
    cleanup()
    assert "--sandbox" in cmd


# --- end to end: static path (subprocess runner) ------------------------------


def test_static_export_ships_loadable_module(tmp_path: Path) -> None:
    nb = _write_nb(tmp_path)
    exported = export_notebook(nb)
    assert exported.esm_by_model, "runner must harvest the widget's module from the session view"
    url = next(iter(exported.esm_by_model.values()))
    assert url.startswith("data:text/javascript")

    md = cells_to_markdown(exported)
    assert 'class="marimo-book-anywidget"' in md
    assert "data-js-url" in md
    # The mount's URL is the harvested one (JSON-encoded attribute).
    assert json.dumps(url)[1:-1][:40] in md


# --- end to end: WASM path (islands generator) --------------------------------


def test_wasm_page_ships_loadable_module(tmp_path: Path) -> None:
    _write_nb(tmp_path)
    book = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py", "mode": "wasm"}]})
    out_dir = tmp_path / "_site_src"
    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report.errors, report.errors
    staged = (out_dir / "docs" / "index.md").read_text(encoding="utf-8")
    assert 'class="marimo-book-anywidget"' in staged
    assert "data-js-url" in staged and "data:text/javascript" in staged
