"""Unit tests for the preprocessor transforms."""

from __future__ import annotations

from pathlib import Path

from marimo_book.config import Book
from marimo_book.launch_buttons import render_button_row
from marimo_book.transforms.callouts import render_callout_html
from marimo_book.transforms.marimo_export import (
    cells_to_markdown,
    export_notebook,
)
from marimo_book.transforms.md_roles import (
    apply_md_transforms,
    rewrite_download_roles,
    strip_glossary_fences,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- md_roles ---------------------------------------------------------------


def test_rewrite_download_role_with_text() -> None:
    md = "See {download}`slides <lectures/foo.pdf>` for context."
    out = rewrite_download_roles(md)
    assert "[slides](lectures/foo.pdf)" in out
    assert "{download}" not in out


def test_rewrite_download_role_without_text_uses_filename() -> None:
    md = "See {download}` <lectures/bar.pdf>` for context."
    out = rewrite_download_roles(md)
    assert "[bar.pdf](lectures/bar.pdf)" in out


def test_strip_glossary_fences_preserves_definition_list() -> None:
    md = """
:::{glossary}
marimo
: A reactive notebook.
:::
""".lstrip()
    out = strip_glossary_fences(md)
    assert ":::{glossary}" not in out
    assert out.count("\n:::\n") == 0  # closing fence removed
    assert "marimo\n: A reactive notebook." in out


def test_apply_md_transforms_runs_both() -> None:
    md = """See {download}`here <foo.pdf>`.

:::{glossary}
term
: def
:::
"""
    out = apply_md_transforms(md)
    assert "[here](foo.pdf)" in out
    assert ":::" not in out


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
    assert row == ""  # no repo → no buttons to derive URLs from


# --- end-to-end marimo_export -----------------------------------------------


def test_simple_notebook_renders_expected_sections() -> None:
    exp = export_notebook(FIXTURES / "simple_notebook.py")
    md = cells_to_markdown(exp)
    assert "# Simple Notebook" in md
    assert "```python\nx = 2 + 3" in md  # code fence visible
    assert "admonition info marimo-book-callout" in md  # callout translated
    # The hidden import cell should not leak into the output.
    assert "import marimo as mo" not in md
