"""Tests for WASM page title hoisting (extract_and_strip_title + render)."""

from __future__ import annotations

import textwrap

import pytest

from marimo_book.transforms.wasm import extract_and_strip_title, render_wasm_page


def _nb(md_cell: str) -> str:
    return (
        "import marimo\n"
        "app = marimo.App()\n\n\n"
        "@app.cell\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo):\n"
        f"{textwrap.indent(md_cell, '    ')}\n"
        "    return\n"
    )


def test_extracts_and_strips_leading_h1():
    src = _nb('mo.md(r"""\n# My Title\n*Written by X*\n""")')
    title, stripped = extract_and_strip_title(src)
    assert title == "My Title"
    assert "# My Title" not in stripped
    assert "*Written by X*" in stripped  # only the H1 line is removed


def test_keeps_descriptive_title_verbatim():
    src = _nb('mo.md(r"""\n# MR Physics: From Protons to Brain Images\nbody\n""")')
    title, _ = extract_and_strip_title(src)
    assert title == "MR Physics: From Protons to Brain Images"


def test_no_h1_first_line_is_left_untouched():
    src = _nb('mo.md(r"""\nJust a paragraph, no heading.\n## later h2\n""")')
    title, stripped = extract_and_strip_title(src)
    assert title is None
    assert stripped == src


def test_h2_is_not_treated_as_title():
    # `## ` must not match — the page has no H1 to hoist.
    src = _nb('mo.md(r"""\n## Section only\n""")')
    assert extract_and_strip_title(src)[0] is None


def test_no_mo_md_returns_unchanged():
    src = "import marimo\napp = marimo.App()\n"
    assert extract_and_strip_title(src) == (None, src)


@pytest.mark.parametrize("quote", ['"""', "'''"])
def test_both_triple_quote_styles(quote):
    src = _nb(f"mo.md(r{quote}\n# Quoted Title\ntext\n{quote})")
    assert extract_and_strip_title(src)[0] == "Quoted Title"


def test_works_on_ast_unparsed_source():
    # The WASM pep723 staging round-trips the source through ast.unparse, which
    # turns mo.md(r\"\"\"...\"\"\") into a single-quoted literal with \n escapes.
    # The title logic must still find + strip the heading (regression: it didn't).
    import ast

    src = _nb('mo.md(r"""\n# Staged Title\nbody\n""")')
    staged = ast.unparse(ast.parse(src))
    assert 'mo.md(r"""' not in staged  # confirm it's the escaped single-quote form
    title, stripped = extract_and_strip_title(staged)
    assert title == "Staged Title"
    assert "# Staged Title" not in ast.unparse(ast.parse(stripped))


def test_render_wasm_page_emits_single_hoisted_h1(tmp_path):
    nb = tmp_path / "page.py"
    nb.write_text(_nb('mo.md(r"""\n# Page Title\n\nHello world.\n""")'), encoding="utf-8")
    body = render_wasm_page(nb)
    # Exactly one real, un-encoded <h1> — the hoisted title — which MkDocs
    # Material detects so it won't inject a duplicate.
    assert body.count("<h1>") == 1
    assert "<h1>Page Title</h1>" in body
    # The notebook's own (islands-encoded) heading must be gone.
    assert "Page Title" not in body.split("</h1>", 1)[1]
