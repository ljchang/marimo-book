"""WASM tables and math follow the dark scheme.

Two marimo scoping gaps left island output light on a dark page. Table
stripes come from marimo's Radix scales, scoped ``.marimo .dark``, which never
matches the ``dark`` class syncMarimoTheme puts on <body>: odd rows stayed
``--lime-2`` under white text. Math, callouts, UI elements and data tables render inside
shadow roots, each with its own ``.marimo`` wrapper that resolves marimo's
colour tokens light, so their text stayed near-black. There is no JS test
runner here; these pin the parts the fix depends on. It was checked against
the live runtime in a browser (100 of 100 marimo shadow roots patched, text
in each matching the scheme, and a live scheme toggle re-theming them).
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


def test_shadow_roots_flip_marimos_own_wrapper_to_dark():
    # marimo declares its colour tokens on the `.marimo` wrapper inside each
    # root; flipping the light/dark toggle there is what resolves them dark.
    # Page CSS can't cross the shadow boundary, so it has to be adopted.
    assert ":host .marimo { --csstools-color-scheme--light: ; color-scheme: dark; }" in JS
    themed = _function("themeShadowRoots")
    assert "adoptedStyleSheets" in themed
    # Idempotent by sheet membership, so a reassigned list gets it back.
    assert "adoptedStyleSheets.includes(_shadowSheet)" in themed
    # Every marimo element, not just math: callouts, dropdowns, tables...
    assert 'startsWith("MARIMO-")' in themed


def test_nested_roots_are_reached():
    # Math inside a callout lives in a root inside a root.
    themed = _function("themeShadowRoots")
    assert "themeShadowRoots(sr)" in themed
    assert "_shadowObserver.observe(sr" in themed


def test_one_shared_sheet_follows_the_scheme_toggle():
    # applyMarimoTheme runs at boot and on every scheme change; rewriting the
    # shared sheet re-themes every adopted root at once.
    assert "syncShadowSheet();" in _function("applyMarimoTheme")
    assert "replaceSync(isDarkScheme() ? SHADOW_DARK_CSS" in _function("syncShadowSheet")


def test_roots_are_patched_when_defined_and_on_re_render():
    watch = _function("watchShadowRoots")
    assert "customElements.whenDefined(tag)" in watch
    assert ":not(:defined)" in watch
    assert "new MutationObserver" in watch and "themeShadowRoots(n)" in watch
    assert "watchShadowRoots();" in _function("bootAll")
