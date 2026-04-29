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
    keep_marimo_controls: bool = False,
    notebook_source: str | None = None,
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

    ``keep_marimo_controls=True`` is set by the WASM render path: in that
    mode marimo's own runtime serves ``<marimo-slider>`` /
    ``<marimo-dropdown>`` etc. as live, kernel-backed controls — they
    must NOT be stripped. We still rewrap anywidgets (because marimo's
    runtime refuses to load anywidget modules from data URLs) but leave
    every other custom element in place.

    ``notebook_source`` (full ``.py`` text): when provided, an extra pass
    cross-references the AST against the rendered HTML to emit
    ``data-driven-by`` JSON on each anywidget mount. The map is
    ``{trait_name: ui_element_object_id}`` so ``marimo_book.js`` can pull
    the live slider value from the runtime's UIElementRegistry on
    ``rerender()`` and propagate it to the widget's local model. Without
    this, the static-shim model only ever shows the build-time defaults
    even when the user moves a slider.
    """
    if (
        "marimo-anywidget" not in raw_html
        and "marimo-ui-element" not in raw_html
        and "marimo-plotly" not in raw_html
    ):
        return raw_html

    soup = BeautifulSoup(raw_html, "lxml")
    classes_used, literal_state = _extract_widget_state(cell_source) if cell_source else ([], {})
    defaults: dict = {}
    if widget_defaults:
        for cls in classes_used:
            for k, v in (widget_defaults.get(cls) or {}).items():
                defaults[k] = v
    seeded_state = {**defaults, **literal_state}

    # Pass 1: rewrap <marimo-anywidget> → <div class="marimo-book-anywidget">.
    for node in list(soup.find_all("marimo-anywidget")):
        _rewrap_anywidget(node, soup, seeded_state)

    # Pass 2: rewrap <marimo-plotly data-figure='{json}'> → mount div.
    # The marimo_book.js shim loads Plotly.js on first hit and renders.
    for node in list(soup.find_all("marimo-plotly")):
        _rewrap_plotly(node, soup)

    # Pass 2b: when full notebook source is provided (WASM mode), emit a
    # data-driven-by map on each anywidget mount so the JS shim can wire
    # rerender() to live UIElementRegistry values.
    if notebook_source:
        _inject_widget_drivers(soup, notebook_source)

    if not keep_marimo_controls:
        # Pass 3: unwrap or drop <marimo-ui-element> wrappers.
        for wrapper in list(soup.find_all("marimo-ui-element")):
            _handle_ui_wrapper(wrapper)

        # Pass 4: drop any remaining standalone control elements that slipped
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
    for attr in (
        "data-js-url",
        "data-js-hash",
        "data-initial-value",
        "data-model-id",
        "data-label",
    ):
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


def _rewrap_plotly(node: Tag, soup: BeautifulSoup) -> None:
    """Convert ``<marimo-plotly data-figure='{json}'>`` into a static mount.

    Marimo serialises a Plotly figure as a custom element with the entire
    figure spec inlined as a JSON string on ``data-figure``. Our static
    site has no marimo runtime, so we rewrap as
    ``<div class="marimo-book-plotly" data-figure='{json}'>`` and let the
    :file:`marimo_book.js` shim fetch Plotly.js from a CDN on first hit
    and call ``Plotly.newPlot`` per mount.
    """
    div = soup.new_tag("div", attrs={"class": "marimo-book-plotly"})
    for attr in ("data-figure", "data-config"):
        val = node.get(attr)
        if val is not None:
            div[attr] = val
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
        for k, v in zip(node.keys, node.values, strict=True):
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
        d.name == "div" and (set(d.get("class") or []) & _MOUNT_CLASSES) for d in descendants
    )
    non_control_descendants = [d for d in descendants if d.name not in _STANDALONE_CONTROLS]
    if has_mount or non_control_descendants:
        wrapper.unwrap()
    else:
        wrapper.decompose()


# --- module-level convenience -----------------------------------------------


# Mount-class names emitted by `_rewrap_anywidget` and `_rewrap_plotly`;
# `_handle_ui_wrapper` checks for these to decide whether to unwrap or
# decompose a `<marimo-ui-element>` parent.
_MOUNT_CLASSES = frozenset({"marimo-book-anywidget", "marimo-book-plotly"})

_ANYWIDGET_SENTINEL = re.compile(r"<marimo-(anywidget|ui-element|plotly)\b", re.IGNORECASE)


def contains_anywidget(raw_html: str) -> bool:
    """Quick test used to skip the BeautifulSoup parse when nothing matches."""
    return bool(_ANYWIDGET_SENTINEL.search(raw_html))


# --- WASM driver injection --------------------------------------------------
#
# In WASM mode the static-shim mount in marimo_book.js creates a LOCAL JS
# model from data-initial-value. Marimo's runtime emits {model_id: ...} for
# anywidget — opaque, useless for static. So slider drives never reach the
# widget's animation loop; the cube doesn't move when the user drags.
#
# Bridge: at build time, AST-extract from each widget construction call the
# `trait=var.value` kwargs, find each slider's rendered <marimo-ui-element>
# by matching its data-label against the slider's source-side label kwarg,
# and emit `data-driven-by='{"trait": "object-id", ...}'` on the mount. The
# JS shim's rerender() (called by marimo's runtime on each cell re-execution)
# reads the map, looks up live values via UIElementRegistry.lookupValue(), and
# applies them as model.set(trait, value). The widget's `model.on("change:…")`
# handlers + rAF loop pick up the new values and the canvas re-renders.

_UI_CONTROL_FUNCS = frozenset(
    {
        "slider", "switch", "dropdown", "radio", "number", "text",
        "checkbox", "multiselect", "date", "datetime",
    }
)


def _inject_widget_drivers(soup: BeautifulSoup, notebook_source: str) -> None:
    """Emit `data-driven-by` on each `<div class="marimo-book-anywidget">`."""
    try:
        tree = ast.parse(notebook_source)
    except SyntaxError:
        return

    # Pass 1: scan AST for slider definitions and widget constructions.
    var_to_label: dict[str, str] = {}
    widget_drivers_in_order: list[dict[str, str]] = []
    for cell_func in _iter_app_cell_functions(tree):
        for child in ast.walk(cell_func):
            # `var = mo.ui.<control>(label="...")` — record var → label.
            if (
                isinstance(child, ast.Assign)
                and len(child.targets) == 1
                and isinstance(child.targets[0], ast.Name)
                and isinstance(child.value, ast.Call)
                and _is_ui_control_call(child.value)
            ):
                label = _extract_label_kwarg(child.value)
                if label is not None:
                    var_to_label[child.targets[0].id] = label
            # `WidgetClass(trait=var.value, ...)` or `WidgetClass(trait=float(var.value), ...)`.
            if isinstance(child, ast.Call):
                name = _call_name(child)
                if name and _WIDGET_NAME_RE.match(name):
                    drivers: dict[str, str] = {}
                    for kw in child.keywords:
                        if kw.arg is None:
                            continue
                        var_ref = _extract_value_var_ref(kw.value)
                        if var_ref is not None:
                            drivers[kw.arg] = var_ref
                    if drivers:
                        widget_drivers_in_order.append(drivers)

    if not widget_drivers_in_order:
        return

    # Pass 2: walk rendered HTML for sliders/controls inside <marimo-ui-element>.
    # Build label → object_id by matching the wrapped control's data-label.
    label_to_object_id: dict[str, str] = {}
    for ui_el in soup.find_all("marimo-ui-element"):
        obj_id = ui_el.get("object-id")
        if not obj_id:
            continue
        ctrl = next(
            (
                c
                for c in ui_el.find_all(True, recursive=True)
                if c.name and c.name.startswith("marimo-")
                and c.name.split("-", 1)[1] in _UI_CONTROL_FUNCS
            ),
            None,
        )
        if ctrl is None:
            continue
        raw_label = ctrl.get("data-label")
        text = _decode_marimo_attr_label(raw_label)
        if text:
            # First wins — labels should be unique within a page.
            label_to_object_id.setdefault(text, obj_id)

    # Pass 3: pair anywidget mounts (in DOM order) to widget constructions
    # (in AST order) and emit data-driven-by.
    mounts = soup.find_all("div", class_="marimo-book-anywidget")
    for mount, drivers in zip(mounts, widget_drivers_in_order):
        resolved: dict[str, str] = {}
        for trait, var_name in drivers.items():
            label = var_to_label.get(var_name)
            if not label:
                continue
            obj_id = label_to_object_id.get(label)
            if obj_id:
                resolved[trait] = obj_id
        if resolved:
            mount["data-driven-by"] = json.dumps(resolved)


def _iter_app_cell_functions(tree: ast.AST):
    """Yield every `@app.cell` (or `@app.cell(...)`) decorated function."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for dec in node.decorator_list:
            target = dec.func if isinstance(dec, ast.Call) else dec
            if isinstance(target, ast.Attribute) and target.attr == "cell":
                yield node
                break


def _is_ui_control_call(call: ast.Call) -> bool:
    """Match `mo.ui.slider(...)` / `mo.ui.switch(...)` / etc."""
    func = call.func
    if not isinstance(func, ast.Attribute):
        return False
    if func.attr not in _UI_CONTROL_FUNCS:
        return False
    parent = func.value
    return (
        isinstance(parent, ast.Attribute)
        and parent.attr == "ui"
        and isinstance(parent.value, ast.Name)
        and parent.value.id == "mo"
    )


def _extract_label_kwarg(call: ast.Call) -> str | None:
    """Pull a string-literal `label=` kwarg from a control constructor."""
    for kw in call.keywords:
        if kw.arg == "label" and isinstance(kw.value, ast.Constant) and isinstance(
            kw.value.value, str
        ):
            return kw.value.value
    return None


def _extract_value_var_ref(node: ast.expr) -> str | None:
    """For `var.value`, `float(var.value)`, etc., return ``var``'s name.

    Recognised forms:
      - ``Name.value``                 → "Name"
      - ``float(Name.value)`` (or int/bool/str) → "Name"
    """
    # var.value
    if (
        isinstance(node, ast.Attribute)
        and node.attr == "value"
        and isinstance(node.value, ast.Name)
    ):
        return node.value.id
    # float(var.value) / int(...) / bool(...) / str(...)
    if (
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id in {"float", "int", "bool", "str"}
        and len(node.args) == 1
    ):
        return _extract_value_var_ref(node.args[0])
    return None


def _decode_marimo_attr_label(raw: str | None) -> str | None:
    """Marimo's `data-label` is a JSON-encoded HTML fragment wrapping the label.

    Example raw value:
        ``"<span class=\"...\"><span class=\"paragraph\">Translate X</span></span>"``

    Returns the inner text (e.g. ``"Translate X"``), or None if undecodable.
    """
    if not raw:
        return None
    try:
        decoded = json.loads(raw)
    except (json.JSONDecodeError, ValueError):
        decoded = raw
    if not isinstance(decoded, str):
        return None
    fragment = BeautifulSoup(decoded, "lxml")
    text = fragment.get_text(strip=True)
    return text or None
