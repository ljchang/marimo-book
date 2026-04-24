"""Translate ``<marimo-anywidget>`` custom elements into a static mount.

Marimo's HTML export inlines each anywidget's ES module as a base64 data URL
on the ``data-js-url`` attribute. We rewrap the element as a plain ``<div
class="marimo-book-anywidget">`` carrying the same attributes. At page load
the :file:`marimo_book.js` shim finds each mount, dynamically imports the
module, wires up a minimal anywidget-compatible ``model`` object, and calls
``module.default.render({model, el})``.

Also strips stray ``<marimo-ui-element>`` / ``<marimo-slider>`` /
``<marimo-switch>`` / ``<marimo-dropdown>`` / ``<marimo-radio>`` wrappers
that would otherwise leak through — these are interactive controls that
require marimo's kernel and have no static meaning.
"""

from __future__ import annotations

import ast
import json
import re

from bs4 import BeautifulSoup
from bs4.element import Tag

# marimo UI elements that make no sense in a static site. When an
# <marimo-ui-element> wraps *only* one of these, drop the whole thing.
_STANDALONE_CONTROLS = {
    "marimo-slider",
    "marimo-switch",
    "marimo-dropdown",
    "marimo-radio",
    "marimo-number",
    "marimo-text",
    "marimo-button",
    "marimo-checkbox",
    "marimo-multiselect",
    "marimo-form",
}


def rewrite_anywidget_html(
    raw_html: str,
    *,
    cell_source: str | None = None,
    widget_defaults: dict | None = None,
) -> str:
    """Rewrite marimo custom elements for static rendering.

    - ``<marimo-anywidget ...>`` → ``<div class="marimo-book-anywidget" ...>``
      preserving data attributes so :file:`marimo_book.js` can rehydrate.
    - ``<marimo-ui-element>`` wrappers are unwrapped (contents preserved)
      when they contain an anywidget, dropped entirely when they only
      contain interactive controls with no static analog.

    Initial widget state is resolved in this precedence order (later wins):

    1. ``widget_defaults[ClassName]`` from ``book.yml``
    2. Literal kwargs parsed out of ``cell_source`` by :mod:`ast`
    3. Anything marimo itself inlined into ``data-initial-value`` (rare for
       static exports — usually just a ``model_id`` reference)
    """
    if "marimo-anywidget" not in raw_html and "marimo-ui-element" not in raw_html:
        return raw_html

    soup = BeautifulSoup(raw_html, "lxml")
    classes_used, literal_state = (
        _extract_widget_state(cell_source) if cell_source else ([], {})
    )
    defaults: dict = {}
    if widget_defaults:
        for cls in classes_used:
            for k, v in (widget_defaults.get(cls) or {}).items():
                defaults[k] = v
    seeded_state = {**defaults, **literal_state}

    # Pass 1: rewrap <marimo-anywidget> → <div class="marimo-book-anywidget">.
    for node in list(soup.find_all("marimo-anywidget")):
        _rewrap_anywidget(node, soup, seeded_state)

    # Pass 2: unwrap or drop <marimo-ui-element> wrappers.
    for wrapper in list(soup.find_all("marimo-ui-element")):
        _handle_ui_wrapper(wrapper)

    # Pass 3: drop any remaining standalone control elements that slipped
    # past (e.g. <marimo-slider> appearing at top level outside a wrapper).
    for ctrl_name in _STANDALONE_CONTROLS:
        for node in list(soup.find_all(ctrl_name)):
            node.decompose()

    # lxml wraps fragments in <html><body>; unwrap for return.
    body = soup.find("body")
    if body is not None:
        return body.decode_contents()
    return str(soup)


# --- helpers -----------------------------------------------------------------


def _rewrap_anywidget(
    node: Tag,
    soup: BeautifulSoup,
    seeded_state: dict,
) -> None:
    """Convert ``<marimo-anywidget>`` into our static mount div.

    If ``seeded_state`` has literal kwargs harvested from the Python source,
    merge them into ``data-initial-value`` so the widget's JS sees them when
    it calls ``model.get("key")``.
    """
    div = soup.new_tag("div", attrs={"class": "marimo-book-anywidget"})
    for attr in ("data-js-url", "data-js-hash", "data-initial-value", "data-model-id", "data-label"):
        val = node.get(attr)
        if val is not None:
            div[attr] = val
    # Merge seeded state into data-initial-value. BeautifulSoup applies HTML
    # entity encoding (&quot;, etc.) when it serialises the attribute, so we
    # emit plain JSON here — matching marimo's own encoding convention.
    if seeded_state:
        initial = _parse_initial_attr(div.get("data-initial-value"))
        if initial is None:
            initial = {}
        merged = {**seeded_state, **initial}  # explicit initial wins
        div["data-initial-value"] = json.dumps(merged)
    for child in list(node.children):
        div.append(child.extract())
    node.replace_with(div)


def _parse_initial_attr(raw: str | None) -> dict | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        return None
    if not isinstance(value, dict):
        return None
    # Marimo emits {"model_id": "..."} when there's no literal state to
    # embed; that's a reference to the runtime's model registry and
    # meaningless for static sites.
    if list(value.keys()) == ["model_id"]:
        return {}
    return value


def _extract_widget_state(cell_source: str) -> tuple[list[str], dict]:
    """Harvest widget class names + literal kwargs from a cell.

    Walks the cell's AST and finds ``Call(func=Name(id=<CamelCase>), ...)``
    nodes where the class name matches :data:`_WIDGET_NAME_RE`. Returns the
    list of class names encountered (for looking up defaults) and a dict of
    literal kwargs. Keeps only literal values (ints, floats, bools, strings,
    None, lists, dicts) so unsafe expressions can't leak into
    ``data-initial-value``.
    """
    try:
        tree = ast.parse(cell_source)
    except SyntaxError:
        return [], {}

    classes: list[str] = []
    state: dict = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = _call_name(node)
        if not name or not _WIDGET_NAME_RE.match(name):
            continue
        classes.append(name)
        for kw in node.keywords:
            if kw.arg is None:
                continue
            value = _literal_value(kw.value)
            if value is _SENTINEL:
                continue
            state[kw.arg] = value
    return classes, state


_SENTINEL = object()
_WIDGET_NAME_RE = re.compile(r"^[A-Z][A-Za-z0-9]*(Widget|View|Mount)$")


def _call_name(call: ast.Call) -> str | None:
    """Return a simple class name for ``Call`` nodes we recognise."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _literal_value(node: ast.expr):
    """Return a JSON-friendly Python value for a literal AST node."""
    if isinstance(node, ast.Constant) and isinstance(
        node.value, (str, int, float, bool, type(None))
    ):
        return node.value
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        inner = _literal_value(node.operand)
        if isinstance(inner, (int, float)):
            return -inner
    if isinstance(node, ast.List):
        out = []
        for el in node.elts:
            v = _literal_value(el)
            if v is _SENTINEL:
                return _SENTINEL
            out.append(v)
        return out
    if isinstance(node, ast.Dict):
        out_d: dict = {}
        for k, v in zip(node.keys, node.values):
            if not isinstance(k, ast.Constant) or not isinstance(k.value, str):
                return _SENTINEL
            lv = _literal_value(v)
            if lv is _SENTINEL:
                return _SENTINEL
            out_d[k.value] = lv
        return out_d
    return _SENTINEL


def _handle_ui_wrapper(wrapper: Tag) -> None:
    """Unwrap or drop a ``<marimo-ui-element>``.

    - If it contains an anywidget mount (after pass 1), unwrap to keep the
      mount visible.
    - If it contains only standalone controls, drop the whole wrapper.
    - Otherwise unwrap — the wrapper itself has no rendering.
    """
    descendants = list(wrapper.find_all(True))
    has_mount = any(
        d.name == "div" and "marimo-book-anywidget" in (d.get("class") or [])
        for d in descendants
    )
    non_control_descendants = [
        d for d in descendants if d.name not in _STANDALONE_CONTROLS
    ]
    if has_mount or non_control_descendants:
        wrapper.unwrap()
    else:
        wrapper.decompose()


# --- module-level convenience -----------------------------------------------


_ANYWIDGET_SENTINEL = re.compile(r"<marimo-(anywidget|ui-element)\b", re.IGNORECASE)


def contains_anywidget(raw_html: str) -> bool:
    """Quick test used to skip the BeautifulSoup parse when nothing matches."""
    return bool(_ANYWIDGET_SENTINEL.search(raw_html))
