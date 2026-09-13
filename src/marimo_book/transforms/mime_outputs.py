"""Static renderers for marimo outputs that have no HTML form of their own.

marimo's kernel formats some values as *non-HTML* MIME bundles and leaves
the drawing to its frontend. On a static page nothing renders them (#73):

- ``application/json`` — a bare ``list`` / ``tuple`` / ``dict`` as the last
  expression of a cell (``marimo._output.formatters.structures``). Values
  JSON cannot carry losslessly ride inside strings: leaves as
  ``text/plain+<type>:<payload>`` (``float``, ``bigint``, ``set``,
  ``frozenset``, ``tuple``), non-string dict keys as
  ``text/plain+<type>:<repr>`` (``int``, ``bool``, ``none``, ``float``,
  ``tuple``, ``frozenset``; a *string* key that happens to start with the
  prefix is escaped as ``text/plain+str:``), and nested rich objects as
  ``<mime>:<data>`` (``text/html:<b>x</b>``, ``image/png:data:…``).
- ``application/vnd.vega*.v*+json`` — an Altair chart as a Vega / Vega-Lite
  spec.
- ``application/vnd.marimo+mimebundle`` — a JSON dict of several of the
  above.

Inside a container (``mo.vstack``, ``mo.hstack``, …) the same values arrive
as ``<marimo-json-output data-json-data='…'>`` and
``<marimo-mime-renderer data-mime='…' data-data='…'>`` custom elements;
:mod:`.anywidgets` rewraps those through the same functions.

A JSON structure becomes a fully static ``<ul>`` tree (Python-flavoured
leaves, like marimo's own viewer with ``value_types="python"``). A Vega
spec becomes ``<div class="marimo-book-vega" data-spec='…'>``, which
``marimo_book.js`` hydrates with vega-embed from a CDN on first sight —
the same lazy-CDN pattern as Plotly figures.
"""

from __future__ import annotations

import html
import json
import re
from typing import Any

VEGA_MIME_TYPES: frozenset[str] = frozenset(
    {
        "application/vnd.vega.v5+json",
        "application/vnd.vegalite.v5+json",
        "application/vnd.vega.v6+json",
        "application/vnd.vegalite.v6+json",
    }
)

MIMEBUNDLE_MIME = "application/vnd.marimo+mimebundle"
_METADATA_KEY = "__metadata__"

_TYPED_LEAF_RE = re.compile(r"^text/plain\+([a-z]+):(.*)$", re.DOTALL)
# Nested rich objects: ``<mime>:<data>``. Deliberately restricted to the
# MIME families marimo's formatters emit so an ordinary string such as
# ``"ratio a/b: 3"`` is never mistaken for one.
_MIME_LEAF_RE = re.compile(
    r"^(text/(?:plain|html|markdown|latex|csv)|application/json"
    r"|application/vnd\.[\w.+-]+|image/[\w.+-]+|video/[\w.+-]+):(.*)$",
    re.DOTALL,
)


# --- public API --------------------------------------------------------------


def render_mime_fragment(mime: str, data: str) -> str | None:
    """Static HTML for one ``(mime, data)`` pair, or ``None`` if unsupported.

    Used for bare MIME bundles (via :mod:`.marimo_export`), for
    ``<marimo-mime-renderer>`` elements, and for rich leaves nested inside a
    JSON structure. ``text/html`` is returned verbatim — the caller decides
    whether it needs the custom-element rewriter.
    """
    if mime == "text/html":
        return data
    if mime == "application/json":
        try:
            value = json.loads(data)
        except ValueError:
            return _pre(data)
        return render_json_tree(value)
    if mime in VEGA_MIME_TYPES:
        return render_vega_mount(data, mime)
    if mime == MIMEBUNDLE_MIME:
        return render_mimebundle(data)
    if mime.startswith(("image/", "video/")):
        return _render_media(mime, data)
    if mime == "text/markdown":
        return render_markdown(data) if data.strip() else ""
    if mime in {"text/plain", "text/latex", "text/csv"}:
        return _pre(data) if data.strip() else ""
    return None


_md_renderer = None


def render_markdown(data: str) -> str:
    """Static HTML for a ``text/markdown`` payload.

    marimo ships ``mo.md`` under ``text/markdown`` but the payload is the
    *already rendered* HTML (``<span class="markdown …">``) — it picks that
    mime so its frontend sanitises the markup rather than because the text
    is markdown source. Treat a payload that starts with a tag as HTML and
    pass it through verbatim (an HTML-escaped tag is unescaped first);
    render anything else as markdown source with the same Python-Markdown
    extension stack mkdocs uses for the page body, so genuine markdown
    (``_repr_markdown_`` objects, ``mo.md`` exported non-interactively)
    lands as prose instead of a ``<pre>`` of raw markup.
    """
    global _md_renderer
    text = data.strip()
    if text.startswith("&lt;"):
        text = html.unescape(text)
    if text.startswith("<"):
        return text
    if _md_renderer is None:
        import markdown as _md

        from marimo_book.shell import markdown_extensions

        names: list[str] = []
        configs: dict[str, dict] = {}
        for ext in markdown_extensions():
            if isinstance(ext, dict):
                ((name, cfg),) = ext.items()
                names.append(name)
                configs[name] = cfg
            else:
                names.append(ext)
        _md_renderer = _md.Markdown(extensions=names, extension_configs=configs)
    _md_renderer.reset()
    return _md_renderer.convert(text)


def render_mimebundle(data: str) -> str | None:
    """Render an ``application/vnd.marimo+mimebundle`` payload.

    The payload is a JSON object ``{mime: data, "__metadata__": {...}}``;
    we pick the richest entry in the same priority order as a plain bundle.
    """
    try:
        bundle = json.loads(data)
    except ValueError:
        return None
    if not isinstance(bundle, dict):
        return None
    return render_bundle_fragment({k: v for k, v in bundle.items() if k != _METADATA_KEY})


_BUNDLE_PRIORITY: tuple[str, ...] = (
    "text/html",
    "text/markdown",
    *sorted(VEGA_MIME_TYPES),
    "application/json",
    "image/png",
    "image/jpeg",
    "image/gif",
    "image/svg+xml",
    "text/plain",
)


def render_bundle_fragment(bundle: dict[str, Any]) -> str | None:
    """Pick the richest renderable entry of a ``{mime: data}`` dict."""
    for mime in _BUNDLE_PRIORITY:
        if mime in bundle:
            data = bundle[mime]
            if not isinstance(data, str):
                data = json.dumps(data)
            return render_mime_fragment(mime, data)
    return None


def render_vega_mount(spec_text: str, mime: str = "application/vnd.vegalite.v6+json") -> str:
    """``<div class="marimo-book-vega" data-spec='…'>`` for the JS hydrator.

    The spec is re-serialised compactly (Altair pretty-prints it) so large
    datasets don't bloat the page. ``data-mime`` lets the hydrator choose
    Vega vs Vega-Lite mode when the spec carries no ``$schema``.
    """
    try:
        compact = json.dumps(json.loads(spec_text), separators=(",", ":"))
    except ValueError:
        compact = spec_text
    return (
        f'<div class="marimo-book-vega" data-mime="{html.escape(mime, quote=True)}" '
        f'data-spec="{html.escape(compact, quote=True)}"></div>'
    )


def render_json_output(
    json_text: str, *, value_types: str = "python", name: str | None = None
) -> str:
    """Render the payload of ``<marimo-json-output data-json-data='…'>``."""
    try:
        value = json.loads(json_text)
    except ValueError:
        return _pre(json_text)
    return render_json_tree(value, value_types=value_types, name=name)


def render_json_tree(value: Any, *, value_types: str = "python", name: str | None = None) -> str:
    """A static ``<ul>`` tree for a marimo-formatted JSON structure.

    ``value_types="python"`` (marimo's default) shows leaves as Python
    literals (``'text'``, ``True``, ``None``); ``"json"`` shows JSON
    (``"text"``, ``true``, ``null``). Keys are shown bare in both modes,
    like marimo's tree viewer. Non-container top-level values render as a
    single leaf.
    """
    py = value_types != "json"
    parts = ['<div class="marimo-book-json">']
    if name:
        parts.append(f'<span class="mb-json-name">{html.escape(str(name))}</span>')
    if isinstance(value, (list, dict)):
        parts.append(_render_container(value, py, top=True))
    else:
        parts.append(_render_leaf(value, py))
    parts.append("</div>")
    return "".join(parts)


# --- tree rendering ----------------------------------------------------------


def _render_container(value: list | dict, py: bool, *, top: bool = False) -> str:
    if not value:
        return _span("mb-json-punct", "[]" if isinstance(value, list) else "{}")
    items = value.items() if isinstance(value, dict) else enumerate(value)
    out: list[str] = []
    if not top:
        out.append(_container_tag(value))
    out.append("<ul>")
    for key, child in items:
        key_html = _render_key(key, py) if isinstance(value, dict) else _span("mb-json-index", key)
        out.append(f"<li>{key_html}{_span('mb-json-punct', ': ')}{_render_node(child, py)}</li>")
    out.append("</ul>")
    return "".join(out)


def _container_tag(value: list | dict) -> str:
    n = len(value)
    kind = "list" if isinstance(value, list) else "dict"
    return _span("mb-json-tag", f"{kind} · {n} item{'' if n == 1 else 's'}")


def _render_node(value: Any, py: bool) -> str:
    if isinstance(value, (list, dict)):
        return _render_container(value, py)
    return _render_leaf(value, py)


def _render_leaf(value: Any, py: bool) -> str:
    if value is None:
        return _span("mb-json-const", "None" if py else "null")
    if isinstance(value, bool):
        return _span("mb-json-const", ("True" if value else "False") if py else str(value).lower())
    if isinstance(value, (int, float)):
        return _span("mb-json-num", _num_text(value))
    if isinstance(value, str):
        typed = _TYPED_LEAF_RE.match(value)
        if typed:
            return _render_typed_leaf(typed.group(1), typed.group(2), py)
        rich = _MIME_LEAF_RE.match(value)
        if rich:
            return _render_rich_leaf(rich.group(1), rich.group(2), py)
        return _span("mb-json-str", repr(value) if py else json.dumps(value, ensure_ascii=False))
    return _span("mb-json-str", str(value))


def _render_typed_leaf(kind: str, payload: str, py: bool) -> str:
    if kind in {"float", "bigint", "int"}:
        return _span("mb-json-num", payload)
    if kind in {"set", "frozenset", "tuple"}:
        return _render_collection_literal(kind, payload, py)
    if kind == "bool":
        return _span("mb-json-const", payload if py else payload.lower())
    if kind == "none":
        return _span("mb-json-const", "None" if py else "null")
    # ``str`` (escaped literal) and anything newer: show the payload as text.
    return _span("mb-json-str", repr(payload) if py else json.dumps(payload, ensure_ascii=False))


def _render_collection_literal(kind: str, payload: str, py: bool) -> str:
    """``{1, 2}`` / ``frozenset({1, 2})`` / ``(1, 2)`` from a JSON-list payload."""
    try:
        elems = json.loads(payload)
    except ValueError:
        # marimo falls back to ``str(value)`` for non-JSON-safe members.
        return _span("mb-json-str", payload)
    if not isinstance(elems, list):
        return _span("mb-json-str", payload)
    inner = ", ".join(_literal_text(e, py) for e in elems)
    if not py:
        return _span("mb-json-str", f"[{inner}]")
    if kind == "tuple":
        text = f"({inner},)" if len(elems) == 1 else f"({inner})"
    elif kind == "set":
        text = f"{{{inner}}}" if elems else "set()"
    else:
        text = f"frozenset({{{inner}}})" if elems else "frozenset()"
    return _span("mb-json-str", text)


def _literal_text(value: Any, py: bool) -> str:
    """Plain-text literal for a member of a set/tuple payload."""
    if value is None:
        return "None" if py else "null"
    if isinstance(value, bool):
        return ("True" if value else "False") if py else str(value).lower()
    if isinstance(value, (int, float)):
        return _num_text(value)
    if isinstance(value, str):
        typed = _TYPED_LEAF_RE.match(value)
        if typed and typed.group(1) in {"float", "bigint", "int"}:
            return typed.group(2)
        return repr(value) if py else json.dumps(value, ensure_ascii=False)
    return json.dumps(value)


def _num_text(value: int | float) -> str:
    if isinstance(value, float) and value != value:  # nan
        return "nan"
    return repr(value)


def _render_rich_leaf(mime: str, payload: str, py: bool) -> str:
    """A nested object with its own formatter (``<mime>:<data>``)."""
    if mime == "text/plain":
        return _span("mb-json-str", payload)
    if mime == "text/html":
        return f'<span class="mb-json-html">{payload}</span>'
    rendered = render_mime_fragment(mime, payload)
    if rendered:
        return f'<span class="mb-json-rich">{rendered}</span>'
    return _span("mb-json-str", payload)


def _render_key(key: Any, py: bool) -> str:
    text = str(key)
    typed = _TYPED_LEAF_RE.match(text)
    if typed:
        kind, payload = typed.group(1), typed.group(2)
        if kind == "str":
            return _span("mb-json-key", payload)
        if kind == "none":
            return _span("mb-json-key mb-json-const", "None" if py else "null")
        if kind == "bool":
            return _span("mb-json-key mb-json-const", payload if py else payload.lower())
        if kind in {"tuple", "frozenset"}:
            return _render_collection_literal(kind, payload, py).replace(
                'class="mb-json-str"', 'class="mb-json-key"', 1
            )
        return _span("mb-json-key mb-json-num", payload)
    return _span("mb-json-key", text)


# --- small helpers -----------------------------------------------------------


def _render_media(mime: str, data: str) -> str | None:
    src = data.strip()
    if not src.startswith("data:"):
        if not _looks_like_base64(src):
            return None
        src = f"data:{mime};base64,{src.replace(chr(10), '')}"
    src_attr = html.escape(src, quote=True)
    if mime.startswith("video/"):
        return f'<video src="{src_attr}" controls=""></video>'
    return f'<img src="{src_attr}" />'


_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _looks_like_base64(s: str) -> bool:
    return bool(_BASE64_RE.match(s))


def _pre(text: str) -> str:
    return f'<pre class="marimo-book-output-text">{html.escape(text.strip())}</pre>'


def _span(cls: str, text: Any) -> str:
    return f'<span class="{cls}">{html.escape(str(text))}</span>'
