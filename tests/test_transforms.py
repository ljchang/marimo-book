"""Unit tests for the preprocessor transforms."""

from __future__ import annotations

from pathlib import Path

from marimo_book.config import Book
from marimo_book.launch_buttons import render_button_row
from marimo_book.transforms.callouts import render_callout_html
from marimo_book.transforms.marimo_export import (
    _render_markdown_cell,
    _render_mime_bundle,
    cells_to_markdown,
    export_notebook,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- callouts ---------------------------------------------------------------


def test_callout_html_info_to_admonition() -> None:
    raw = (
        "<marimo-callout-output "
        "data-html='\"&lt;span class=\\&quot;markdown prose dark:prose-invert contents\\&quot;&gt;"
        "&lt;span class=\\&quot;paragraph\\&quot;&gt;Hello&lt;/span&gt;&lt;/span&gt;\"' "
        "data-kind='\"info\"'></marimo-callout-output>"
    )
    out = render_callout_html(raw)
    assert out is not None
    assert 'class="admonition info marimo-book-callout"' in out
    assert "Hello" in out


def test_callout_html_warn_kind_maps_to_warning() -> None:
    raw = (
        "<marimo-callout-output "
        "data-html='\"&lt;span&gt;Body&lt;/span&gt;\"' "
        "data-kind='\"warn\"'></marimo-callout-output>"
    )
    out = render_callout_html(raw)
    assert out is not None
    assert "admonition warning" in out


def test_callout_html_returns_none_for_unrelated_html() -> None:
    assert render_callout_html("<div>not a callout</div>") is None


# --- launch buttons ---------------------------------------------------------


def _book_with_repo() -> Book:
    return Book.model_validate(
        {
            "title": "T",
            "repo": "https://github.com/owner/repo",
            "branch": "v2",
            "toc": [{"file": "content/x.py"}],
        }
    )


def test_launch_buttons_marimo_file_has_all_three() -> None:
    b = _book_with_repo()
    row = render_button_row(b, Path("content/x.py"))
    assert "molab.marimo.io/github/owner/repo/blob/v2/content/x.py" in row
    assert "github.com/owner/repo/blob/v2/content/x.py" in row
    assert "raw.githubusercontent.com/owner/repo/v2/content/x.py" in row
    assert 'download="x.py"' in row


def test_launch_buttons_markdown_file_only_github() -> None:
    b = _book_with_repo()
    row = render_button_row(b, Path("content/intro.md"))
    assert "molab" not in row  # not a .py
    assert "Download" not in row
    assert "github.com/owner/repo/blob/v2/content/intro.md" in row


def test_launch_buttons_disabled_when_repo_missing() -> None:
    b = Book.model_validate({"title": "T", "toc": [{"file": "content/x.py"}]})
    row = render_button_row(b, Path("content/x.py"))
    assert row == ""  # all three buttons need a repo URL → empty row


def test_launch_buttons_emit_icons() -> None:
    """Buttons render with inline SVG icons + a screen-reader label."""
    b = _book_with_repo()
    row = render_button_row(b, Path("content/x.py"))
    assert '<svg class="marimo-book-button-icon"' in row
    assert 'class="marimo-book-button-label"' in row


def test_launch_buttons_default_placement_header() -> None:
    """Default placement is 'header' — JS shim relocates into Material's header."""
    b = _book_with_repo()
    row = render_button_row(b, Path("content/x.py"))
    assert 'data-placement="header"' in row


def test_launch_buttons_repo_subpath_prepended_when_book_in_subdir() -> None:
    """When the book lives in a subdirectory of its repo (e.g. docs/), the
    GitHub / molab / raw URLs must include that subpath, otherwise links
    404 against the actual repo layout. Case in point: marimo-book's own
    docs at docs/book.yml — without this, the GitHub button on
    /authoring/ would link to ``.../blob/main/content/authoring.md``
    instead of the correct ``.../blob/main/docs/content/authoring.md``.
    """
    b = _book_with_repo()
    row = render_button_row(b, Path("content/x.py"), repo_subpath="docs")
    assert "molab.marimo.io/github/owner/repo/blob/v2/docs/content/x.py" in row
    assert "github.com/owner/repo/blob/v2/docs/content/x.py" in row
    assert "raw.githubusercontent.com/owner/repo/v2/docs/content/x.py" in row


def test_launch_buttons_repo_subpath_empty_keeps_legacy_behavior() -> None:
    """Empty repo_subpath (the default for books at repo root) leaves URLs
    unchanged — ensures we don't regress dartbrains-style book layouts
    where book.yml IS at the repo root."""
    b = _book_with_repo()
    row = render_button_row(b, Path("content/x.py"), repo_subpath="")
    assert "github.com/owner/repo/blob/v2/content/x.py" in row
    assert "/blob/v2/docs/content" not in row  # no leaked prefix


# --- end-to-end marimo_export -----------------------------------------------


def test_simple_notebook_renders_expected_sections() -> None:
    exp = export_notebook(FIXTURES / "simple_notebook.py")
    md = cells_to_markdown(exp)
    assert "# Simple Notebook" in md
    assert "```python\nx = 2 + 3" in md  # code fence visible
    assert "admonition info marimo-book-callout" in md  # callout translated
    # The hidden import cell should not leak into the output.
    assert "import marimo as mo" not in md


def test_plotly_rewrap_emits_static_mount() -> None:
    """`<marimo-plotly data-figure='{json}'>` rewraps to a div the JS
    shim picks up to hydrate via Plotly.js."""
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    raw = "<marimo-plotly data-figure='{&quot;data&quot;:[],&quot;layout&quot;:{}}' data-config='{}'></marimo-plotly>"
    out = rewrite_anywidget_html(raw)
    assert 'class="marimo-book-plotly"' in out
    assert "marimo-plotly" not in out.replace("marimo-book-plotly", "")  # no original tag left
    assert "data-figure=" in out


def test_wasm_anywidget_emits_data_driven_by_for_slider_kwargs() -> None:
    """In WASM mode, anywidget mounts get a `data-driven-by` JSON map that
    pairs each `WidgetClass(trait=slider.value)` kwarg to the slider's
    rendered ``object-id``. The JS shim's ``rerender()`` reads this map
    and pulls live values from the runtime's UIElementRegistry — without
    it, slider drags never reach the widget's local model in WASM mode.
    """
    import json
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    notebook_src = """
import marimo
app = marimo.App()

@app.cell
def _(mo):
    fwhm_slider = mo.ui.slider(start=0, stop=20, step=0.5, value=0, label="FWHM (mm)")
    return fwhm_slider,

@app.cell
def _(SmoothingWidget, mo, fwhm_slider):
    _w = SmoothingWidget(fwhm=float(fwhm_slider.value))
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return
"""
    # data-label is JSON-encoded HTML in marimo's emitter — match the live shape.
    body = (
        '<marimo-island data-cell-id="x1">'
        '<marimo-ui-element object-id="x1-0">'
        '<marimo-slider data-label=\'"&lt;span class=\\"paragraph\\"&gt;FWHM (mm)&lt;/span&gt;"\'></marimo-slider>'
        '</marimo-ui-element></marimo-island>'
        '<marimo-island data-cell-id="x2">'
        '<marimo-ui-element object-id="x2-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m1"}\' data-js-url=\'"data:..."\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
    )
    out = rewrite_anywidget_html(body, keep_marimo_controls=True, notebook_source=notebook_src)
    # Look for the emitted attribute. BeautifulSoup re-encodes HTML, so we
    # check via re-parse rather than substring match.
    from bs4 import BeautifulSoup
    parsed = BeautifulSoup(out, "lxml")
    mount = parsed.find("div", class_="marimo-book-anywidget")
    assert mount is not None, "anywidget mount should be rewritten to a static div"
    driven_by = mount.get("data-driven-by")
    assert driven_by, f"missing data-driven-by on mount: {mount}"
    parsed_map = json.loads(driven_by)
    assert parsed_map == {"fwhm": "x1-0"}, parsed_map
    # Also emitted on the parent <marimo-ui-element> so it survives partial
    # rewraps that replace the inner div.
    parent_ui = mount.find_parent("marimo-ui-element")
    assert parent_ui is not None
    assert parent_ui.get("data-driven-by") == driven_by, (
        f"parent ui-element should mirror mount's data-driven-by, "
        f"got {parent_ui.get('data-driven-by')!r}"
    )
    # Page-global registry, keyed by object-id — the only thing that
    # survives WASM mode's full island-content rebuild after kernel boot.
    blob = parsed.find(
        "script",
        attrs={"type": "application/json", "class": "marimo-book-anywidget-drivers"},
    )
    assert blob is not None, "global driver registry script blob missing"
    registry = json.loads(blob.string)
    # Keyed by the WIDGET's parent <marimo-ui-element> object-id (x2-0
    # here — x1-0 is the slider's). Each value is the trait→slider-objId
    # map the JS shim applies via UIElementRegistry.lookupValue().
    assert registry == {"x2-0": {"fwhm": "x1-0"}}, registry


def test_wasm_anywidget_handles_typed_kwargs_int_bool_str() -> None:
    """`Widget(t=int(s.value))` / `bool(...)` / `str(...)` resolve the same
    way as bare `s.value` — the cast is transparent for driver mapping.
    """
    import json
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    notebook_src = """
import marimo
app = marimo.App()

@app.cell
def _(mo):
    n_protons_slider = mo.ui.slider(start=10, stop=200, value=100, label="N protons")
    b0_on_toggle = mo.ui.switch(label="B-zero ON")
    return n_protons_slider, b0_on_toggle

@app.cell
def _(NetMagnetizationWidget, mo, n_protons_slider, b0_on_toggle):
    _w = NetMagnetizationWidget(
        n_protons=int(n_protons_slider.value),
        b0_on=bool(b0_on_toggle.value),
    )
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return
"""
    body = (
        '<marimo-island><marimo-ui-element object-id="A-0">'
        '<marimo-slider data-label=\'"N protons"\'></marimo-slider>'
        '</marimo-ui-element>'
        '<marimo-ui-element object-id="A-1">'
        '<marimo-switch data-label=\'"B-zero ON"\'></marimo-switch>'
        '</marimo-ui-element></marimo-island>'
        '<marimo-island><marimo-ui-element object-id="B-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m"}\' data-js-url=\'"data:"\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
    )
    out = rewrite_anywidget_html(body, keep_marimo_controls=True, notebook_source=notebook_src)
    from bs4 import BeautifulSoup
    parsed = BeautifulSoup(out, "lxml")
    mount = parsed.find("div", class_="marimo-book-anywidget")
    parsed_map = json.loads(mount["data-driven-by"])
    assert parsed_map == {"n_protons": "A-0", "b0_on": "A-1"}, parsed_map


def test_wasm_anywidget_signature_disambiguates_same_label_across_widgets() -> None:
    """Two sliders sharing a label but with different ranges resolve to
    distinct object-ids, not whichever happened to render first.

    Concrete case from dartbrains' Preprocessing.py: TransformCubeWidget
    and CostFunctionWidget both label their first slider "Translate X",
    but the cube uses range -15..15 step 0.5 while the cost function uses
    0..20 step 1. Pre-fix, both widgets resolved to the cube's object-id
    because the global label→object-id map was first-wins.
    """
    import json
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    notebook_src = """
import marimo
app = marimo.App()

@app.cell
def _(mo):
    cube_tx = mo.ui.slider(start=-15, stop=15, step=0.5, value=0, label="Translate X")
    cost_tx = mo.ui.slider(start=0, stop=20, step=1, value=0, label="Translate X")
    return cube_tx, cost_tx

@app.cell
def _(TransformCubeWidget, mo, cube_tx):
    _w = TransformCubeWidget(trans_x=float(cube_tx.value))
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return

@app.cell
def _(CostFunctionWidget, mo, cost_tx):
    _w = CostFunctionWidget(trans_x=float(cost_tx.value))
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return
"""
    body = (
        # Slider definition island: two sliders, same label, different ranges
        '<marimo-island data-cell-id="defs">'
        '<marimo-ui-element object-id="defs-0">'
        '<marimo-slider data-label=\'"Translate X"\' data-start="-15" data-stop="15" data-step="0.5"></marimo-slider>'
        '</marimo-ui-element>'
        '<marimo-ui-element object-id="defs-1">'
        '<marimo-slider data-label=\'"Translate X"\' data-start="0" data-stop="20" data-step="1"></marimo-slider>'
        '</marimo-ui-element>'
        '</marimo-island>'
        # TransformCubeWidget mount
        '<marimo-island data-cell-id="cube">'
        '<marimo-ui-element object-id="cube-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m1"}\' data-js-url=\'"data:..."\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
        # CostFunctionWidget mount
        '<marimo-island data-cell-id="cost">'
        '<marimo-ui-element object-id="cost-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m2"}\' data-js-url=\'"data:..."\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
    )
    out = rewrite_anywidget_html(body, keep_marimo_controls=True, notebook_source=notebook_src)
    from bs4 import BeautifulSoup
    parsed = BeautifulSoup(out, "lxml")
    blob = parsed.find("script", attrs={
        "type": "application/json",
        "class": "marimo-book-anywidget-drivers",
    })
    assert blob is not None
    registry = json.loads(blob.string)
    # The fix: each widget resolves to its OWN slider's object-id, not
    # whichever happened to render first.
    assert registry == {
        "cube-0": {"trans_x": "defs-0"},
        "cost-0": {"trans_x": "defs-1"},
    }, registry


def test_wasm_anywidget_resolves_intermediate_local_alias_to_slider() -> None:
    """`_local = slider.value` then `Widget(trait=_local)` resolves the
    same way as `Widget(trait=slider.value)` directly.

    Concrete case from dartbrains MR_Physics.py: PrecessionWidget cells
    pre-extract slider values into intermediate locals before passing
    them as kwargs (e.g. `_b0 = b0_larmor_slider.value;
    PrecessionWidget(b0=_b0, ...)`). Without alias resolution, every
    such widget gets no driver map and the spinning-plot sliders
    silently fail to drive their widget.
    """
    import json
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    notebook_src = """
import marimo
app = marimo.App()

@app.cell
def _(mo):
    b0_larmor_slider = mo.ui.slider(start=0.5, stop=7, step=0.5, value=3, label="B0 (T)")
    return b0_larmor_slider,

@app.cell
def _(PrecessionWidget, b0_larmor_slider, mo):
    _b0 = b0_larmor_slider.value
    _widget = PrecessionWidget(b0=_b0, flip_angle=30.0, show_relaxation=False)
    _wrapped = mo.ui.anywidget(_widget)
    _wrapped
    return
"""
    body = (
        '<marimo-island data-cell-id="d1">'
        '<marimo-ui-element object-id="d1-0">'
        '<marimo-slider data-label=\'"B0 (T)"\' data-start="0.5" data-stop="7" data-step="0.5"></marimo-slider>'
        '</marimo-ui-element></marimo-island>'
        '<marimo-island data-cell-id="w1">'
        '<marimo-ui-element object-id="w1-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m1"}\' data-js-url=\'"data:..."\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
    )
    out = rewrite_anywidget_html(body, keep_marimo_controls=True, notebook_source=notebook_src)
    from bs4 import BeautifulSoup
    parsed = BeautifulSoup(out, "lxml")
    blob = parsed.find("script", attrs={
        "type": "application/json",
        "class": "marimo-book-anywidget-drivers",
    })
    assert blob is not None
    registry = json.loads(blob.string)
    assert registry == {"w1-0": {"b0": "d1-0"}}, registry


def test_wasm_anywidget_zip_alignment_preserved_with_undriven_widgets() -> None:
    """Widgets with no slider kwargs (literal-only) still take a slot in
    the source-order list so subsequent widget→mount pairing stays
    aligned. Without this, every literal-only widget would shift the
    next widget's drivers onto the wrong mount.
    """
    import json
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    notebook_src = """
import marimo
app = marimo.App()

@app.cell
def _(mo):
    speed_slider = mo.ui.slider(start=0.1, stop=2.0, step=0.1, value=1.0, label="Speed")
    return speed_slider,

@app.cell
def _(SomeStaticWidget, mo):
    # No slider kwargs — should occupy a slot but emit no driver map.
    _w = SomeStaticWidget(static_value=42)
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return

@app.cell
def _(SomeDynamicWidget, mo, speed_slider):
    _w = SomeDynamicWidget(speed=float(speed_slider.value))
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return
"""
    body = (
        '<marimo-island><marimo-ui-element object-id="s-0">'
        '<marimo-slider data-label=\'"Speed"\' data-start="0.1" data-stop="2.0" data-step="0.1"></marimo-slider>'
        '</marimo-ui-element></marimo-island>'
        # First widget: literal-only, has no driver map (DOM mount #0)
        '<marimo-island><marimo-ui-element object-id="static-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m1"}\' data-js-url=\'"data:"\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
        # Second widget: speed-driven (DOM mount #1) — its drivers must NOT
        # be paired onto static-0 just because the first widget had no
        # entry to consume.
        '<marimo-island><marimo-ui-element object-id="dynamic-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m2"}\' data-js-url=\'"data:"\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
    )
    out = rewrite_anywidget_html(body, keep_marimo_controls=True, notebook_source=notebook_src)
    from bs4 import BeautifulSoup
    parsed = BeautifulSoup(out, "lxml")
    blob = parsed.find("script", attrs={
        "type": "application/json",
        "class": "marimo-book-anywidget-drivers",
    })
    assert blob is not None
    registry = json.loads(blob.string)
    # The driven widget (dynamic-0) gets the speed-slider mapping.
    # The undriven widget (static-0) does NOT appear in the registry.
    assert registry == {"dynamic-0": {"speed": "s-0"}}, registry


def test_wasm_anywidget_no_driver_map_when_no_slider_kwargs() -> None:
    """Widgets that use only literal kwargs (no `slider.value` references)
    get NO data-driven-by attribute — preserves backwards compatibility
    for the static + precompute path that doesn't need this hook.
    """
    from marimo_book.transforms.anywidgets import rewrite_anywidget_html

    notebook_src = """
import marimo
app = marimo.App()

@app.cell
def _(SomeWidget, mo):
    _w = SomeWidget(static_value=42)
    _wrapped = mo.ui.anywidget(_w)
    _wrapped
    return
"""
    body = (
        '<marimo-island><marimo-ui-element object-id="C-0">'
        '<marimo-anywidget data-initial-value=\'{"model_id":"m"}\' data-js-url=\'"data:"\'></marimo-anywidget>'
        '</marimo-ui-element></marimo-island>'
    )
    out = rewrite_anywidget_html(body, keep_marimo_controls=True, notebook_source=notebook_src)
    assert "data-driven-by" not in out


def test_markdown_cell_preserves_written_by_byline() -> None:
    """Per-notebook ``*Written by …*`` attribution lines must survive
    rendering — they are the canonical Jupyter-Book-era byline and the
    only place per-chapter authorship is recorded in dartbrains."""
    cell = {
        "cell_type": "markdown",
        "source": "# Introduction to GLM\n*Written by Luke Chang*\n\nBody text.",
    }
    out = _render_markdown_cell(cell, strip_duplicate_title=False)
    assert "*Written by Luke Chang*" in out
    assert "# Introduction to GLM" in out
    assert "Body text." in out


def test_markdown_cell_passes_through_when_no_byline() -> None:
    cell = {"cell_type": "markdown", "source": "# Title\n\nJust prose, no byline.\n"}
    out = _render_markdown_cell(cell, strip_duplicate_title=False)
    assert out == "# Title\n\nJust prose, no byline."


def test_anywidget_escaped_under_text_markdown_routes_to_html() -> None:
    """Regression: marimo export sometimes downgrades anywidget HTML to a
    text/markdown bundle with the <marimo-anywidget> tag fully escaped.
    The mime-bundle picker must detect that, unescape, and run the
    rewriter so the static mount div is emitted."""
    bundle = {
        "text/markdown": (
            "&lt;marimo-anywidget data-initial-value=&#x27;{&amp;quot;model_id"
            "&amp;quot;:&amp;quot;abc&amp;quot;}&#x27; "
            "data-js-url=&#x27;&amp;quot;data:text/javascript;base64,QQ==&amp;quot;&#x27;"
            "&gt;&lt;/marimo-anywidget&gt;"
        ),
    }
    out = _render_mime_bundle(
        bundle,
        cell_source="canvas = mo.ui.anywidget(ScatterWidget(height=320))",
    )
    assert 'class="marimo-book-anywidget"' in out
    assert "&lt;marimo-anywidget" not in out
    # Literal kwarg from cell source seeds initial state.
    assert '"height": 320' in out
