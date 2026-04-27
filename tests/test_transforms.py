"""Unit tests for the preprocessor transforms."""

from __future__ import annotations

from pathlib import Path

from marimo_book.config import Book
from marimo_book.launch_buttons import render_button_row
from marimo_book.transforms.callouts import render_callout_html
from marimo_book.transforms.marimo_export import (
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
