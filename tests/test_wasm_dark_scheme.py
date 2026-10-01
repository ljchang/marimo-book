"""WASM tables and math follow the dark scheme.

Two marimo scoping gaps left island output light on a dark page. Table
stripes come from marimo's Radix scales, scoped ``.marimo .dark``, which never
matches the ``dark`` class syncMarimoTheme puts on <body>: odd rows stayed
``--lime-2`` under white text. Math is typeset inside each ``<marimo-tex>``
shadow root, whose own ``.marimo`` wrapper pins the light ``--foreground``, so
every equation stayed near-black. There is no JS test runner here; these pin
the parts the fix depends on. It was checked against the live runtime in a
browser (30 of 30 ``<marimo-tex>`` roots patched after the kernel re-render,
math matching the surrounding text in both schemes).
"""

from __future__ import annotations

from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src" / "marimo_book" / "assets"
JS = (ASSETS / "marimo_book.js").read_text()
CSS = (ASSETS / "extra.css").read_text()


def _function(name: str) -> str:
    start = JS.index(f"function {name}(")
    return JS[start : JS.index("\n  }\n", start)]


def _rule(selector: str) -> str:
    start = CSS.index(selector)
    return CSS[start : CSS.index("}", start)]


def test_island_table_stripes_use_material_tokens():
    # Outranks marimo's `.marimo .markdown table tbody tr:nth-child(...)`
    # by one class, and resolves through the scheme-aware Material tokens.
    odd = _rule(".md-typeset .marimo .markdown table tbody tr:nth-child(odd)")
    even = _rule(".md-typeset .marimo .markdown table tbody tr:nth-child(2n)")
    hover = _rule(".md-typeset .marimo .markdown table tbody tr:hover")
    assert "background: transparent" in odd
    assert "var(--md-default-bg-color--light)" in even
    assert "var(--md-accent-fg-color--transparent)" in hover
    for rule in (odd, even, hover):
        assert "--lime-" not in rule and "--yellow-" not in rule


def test_island_dataframes_get_the_same_stripes():
    assert ".md-typeset .marimo table.dataframe tbody tr:nth-child(odd)" in CSS
    assert ".md-typeset .marimo table.dataframe tbody tr:nth-child(2n)" in CSS
    assert ".md-typeset .marimo table.dataframe tbody tr:hover" in CSS


def test_math_inherits_the_surrounding_text_color():
    # Page CSS can't cross the shadow boundary; the rule has to be adopted
    # into each <marimo-tex> root.
    fn = _function("inheritTexColor")
    assert ":host .marimo { color: inherit; }" in fn
    assert "adoptedStyleSheets" in fn
    # Idempotent by sheet membership, so a reassigned list gets it back.
    assert "adoptedStyleSheets.includes(_texSheet)" in fn


def test_math_roots_are_patched_when_defined_and_on_re_render():
    watch = _function("watchTex")
    assert 'customElements.whenDefined("marimo-tex")' in watch
    assert "new MutationObserver" in watch and "inheritTexColor(" in watch
    assert "watchTex();" in JS
