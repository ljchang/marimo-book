"""Static rendering of non-HTML marimo outputs (#73).

marimo formats a bare list/dict as ``application/json`` (with typed leaf
markers), an Altair chart as a Vega(-Lite) MIME bundle, and both as
``<marimo-json-output>`` / ``<marimo-mime-renderer>`` custom elements when
nested inside a container. None of those rendered on a static page.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from marimo_book.transforms.anywidgets import rewrite_anywidget_html
from marimo_book.transforms.marimo_export import (
    _render_mime_bundle,
    cells_to_markdown,
    export_notebook,
)
from marimo_book.transforms.mime_outputs import (
    render_json_tree,
    render_mime_fragment,
    render_vega_mount,
)

FIXTURES = Path(__file__).parent / "fixtures"


# --- JSON tree (unit) --------------------------------------------------------


def test_bare_list_bundle_renders_tree() -> None:
    out = _render_mime_bundle({"application/json": "[1, 2, 3]"})
    assert 'class="marimo-book-output"' in out
    assert 'class="marimo-book-json"' in out
    assert out.count("<li>") == 3
    assert '<span class="mb-json-num">3</span>' in out


def test_json_tree_decodes_marimo_typed_leaves_python_style() -> None:
    # Exactly what marimo's structures formatter emits for
    # {"f": 1.5, "s": {3}, "fs": frozenset(), "t": (1,), 2: "k", True: 0, None: 1}
    value = {
        "f": "text/plain+float:1.5",
        "big": "text/plain+bigint:123456789012345678901234567890",
        "s": "text/plain+set:[3]",
        "fs": "text/plain+frozenset:[]",
        "t": "text/plain+tuple:[1]",
        "text/plain+int:2": "k",
        "text/plain+bool:True": 0,
        "text/plain+none:": 1,
        "text/plain+str:text/plain+literal": "escaped key",
        "ok": False,
        "none": None,
        "str": "quote'in",
    }
    out = render_json_tree(value)
    assert '<span class="mb-json-num">1.5</span>' in out
    assert "123456789012345678901234567890" in out
    assert '<span class="mb-json-str">{3}</span>' in out
    assert '<span class="mb-json-str">frozenset()</span>' in out
    assert '<span class="mb-json-str">(1,)</span>' in out
    assert '<span class="mb-json-key mb-json-num">2</span>' in out
    assert '<span class="mb-json-key mb-json-const">True</span>' in out
    assert '<span class="mb-json-key mb-json-const">None</span>' in out
    assert '<span class="mb-json-key">text/plain+literal</span>' in out
    assert '<span class="mb-json-const">False</span>' in out
    assert '<span class="mb-json-const">None</span>' in out
    # Python repr for strings, HTML-escaped.
    assert "&quot;quote&#x27;in&quot;" in out


def test_json_tree_json_value_types() -> None:
    out = render_json_tree({"a": True, "b": None, "c": "x"}, value_types="json")
    assert '<span class="mb-json-const">true</span>' in out
    assert '<span class="mb-json-const">null</span>' in out
    assert '<span class="mb-json-str">&quot;x&quot;</span>' in out


def test_json_tree_nested_containers_and_empties() -> None:
    out = render_json_tree({"empty_list": [], "empty_dict": {}, "n": {"k": [1]}})
    assert '<span class="mb-json-punct">[]</span>' in out
    assert '<span class="mb-json-punct">{}</span>' in out
    assert "dict · 1 item</span><ul>" in out
    assert "list · 1 item</span><ul>" in out


def test_json_tree_rich_leaves() -> None:
    out = render_json_tree(
        ["text/html:<b>bold</b>", "image/png:data:image/png;base64,QUJD", "a/b: 3"]
    )
    assert '<span class="mb-json-html"><b>bold</b></span>' in out
    assert '<img src="data:image/png;base64,QUJD" />' in out
    # An ordinary string containing "mime-ish" text is left alone.
    assert "&#x27;a/b: 3&#x27;" in out


def test_json_tree_escapes_html_in_text() -> None:
    out = render_json_tree({"<script>": "<img onerror=x>"})
    assert "<script>" not in out
    assert "<img" not in out


# --- Vega mount (unit) -------------------------------------------------------


def test_vega_bundle_renders_mount_with_compact_spec() -> None:
    spec = {"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "mark": "bar"}
    pretty = json.dumps(spec, indent=2)
    out = _render_mime_bundle({"application/vnd.vegalite.v6+json": pretty})
    assert 'class="marimo-book-vega"' in out
    assert 'data-mime="application/vnd.vegalite.v6+json"' in out
    # Compact (no indentation newlines) and attribute-escaped.
    assert "\n  " not in out.split("data-spec=")[1]
    assert "&quot;mark&quot;:&quot;bar&quot;" in out


def test_vega_mount_keeps_unparseable_spec_verbatim() -> None:
    out = render_vega_mount("not json", "application/vnd.vega.v5+json")
    assert 'data-spec="not json"' in out


def test_marimo_mimebundle_routes_to_richest_entry() -> None:
    bundle = json.dumps(
        {"image/png": "data:image/png;base64,QUJD", "__metadata__": {"image/png": {"width": 1}}}
    )
    out = _render_mime_bundle({"application/vnd.marimo+mimebundle": bundle})
    assert '<img src="data:image/png;base64,QUJD" />' in out


def test_render_mime_fragment_unknown_mime_is_none() -> None:
    assert render_mime_fragment("application/x-unknown", "x") is None


# --- custom elements inside containers (unit) --------------------------------


def test_json_output_element_in_vstack_rewraps_to_tree() -> None:
    raw = (
        "<div style='display: flex'><span>3</span>"
        "<marimo-json-output data-json-data='[1,2,3]' "
        "data-value-types='&quot;python&quot;'></marimo-json-output>"
        "<span>my string</span></div>"
    )
    out = rewrite_anywidget_html(raw)
    assert "marimo-json-output" not in out
    assert 'class="marimo-book-json"' in out
    assert out.count("<li>") == 3
    assert "<span>my string</span>" in out


def test_mime_renderer_element_rewraps_vega_spec() -> None:
    spec = json.dumps({"$schema": "https://vega.github.io/schema/vega-lite/v6.json", "mark": "bar"})
    raw = (
        "<div><marimo-mime-renderer "
        f"data-mime='{json.dumps('application/vnd.vegalite.v6+json').replace(chr(34), '&quot;')}' "
        f"data-data='{json.dumps(spec).replace(chr(34), '&quot;')}'></marimo-mime-renderer></div>"
    )
    out = rewrite_anywidget_html(raw)
    assert "marimo-mime-renderer" not in out
    assert 'class="marimo-book-vega"' in out
    # BeautifulSoup re-serialises the attribute; only the compact spec matters.
    assert '"mark":"bar"' in out.replace("&quot;", '"')


def test_mime_renderer_unsupported_mime_is_dropped() -> None:
    raw = (
        "<div><marimo-mime-renderer data-mime='&quot;application/x-unknown&quot;' "
        "data-data='&quot;x&quot;'></marimo-mime-renderer><span>kept</span></div>"
    )
    out = rewrite_anywidget_html(raw)
    assert "marimo-mime-renderer" not in out
    assert "<span>kept</span>" in out


# --- end to end through marimo's real exporter ------------------------------


def test_structures_notebook_renders_list_and_dict_outputs() -> None:
    md = cells_to_markdown(export_notebook(FIXTURES / "structures_notebook.py"))
    # Bare list: three rows.
    assert md.count('class="marimo-book-json"') == 3
    assert '<span class="mb-json-key">name</span>' in md
    assert "&#x27;Ada&#x27;" in md
    assert '<span class="mb-json-num">1.5</span>' in md
    assert '<span class="mb-json-str">{3}</span>' in md
    assert '<span class="mb-json-key mb-json-num">2</span>' in md
    # Inside mo.vstack the list sat in a <marimo-json-output>; gone now.
    assert "marimo-json-output" not in md
    assert "<span>my string</span>" in md


def test_altair_notebook_renders_vega_mounts() -> None:
    pytest.importorskip("altair")
    md = cells_to_markdown(export_notebook(FIXTURES / "altair_notebook.py"))
    assert md.count('class="marimo-book-vega"') == 2  # bare chart + inside vstack
    assert "marimo-mime-renderer" not in md
    assert "caption under the chart" in md
    assert "vega-lite" in md  # $schema survives into data-spec
