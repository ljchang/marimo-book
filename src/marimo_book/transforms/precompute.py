"""Detect and precompute discrete marimo UI widgets for static reactivity.

The preprocessor calls :func:`scan_widgets` on each marimo notebook's source
to find widget calls whose value set is statically determinable. Candidate
widgets are then driven by ``Preprocessor`` through a per-value re-export
loop (Path X — see the plan); the resulting outputs become a JSON lookup
table embedded in the page, and ``assets/marimo_book.js`` swaps them on
client-side interaction.

This module is **detection + classification only**. The actual re-export
orchestration lives in :mod:`marimo_book.preprocessor` so it can share the
build cache and report counters.

Design summary:

- The widget IS the annotation. Authors write normal marimo code.
- ``mo.ui.slider`` with ``steps=[...]`` or explicit ``step=N`` is a
  candidate. Bare ``mo.ui.slider(0, 10)`` (no step) is treated as
  continuous and rendered static.
- ``mo.ui.dropdown`` / ``switch`` / ``checkbox`` / ``radio`` are
  always discrete; always candidates when precompute is enabled.
- Widgets created via non-literal calls (``make_slider(low, high)``)
  are skipped silently — the value set isn't statically extractable.
"""

from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path
from typing import Any

# marimo widget call patterns we recognise. Keys are the dotted attribute
# path; values name the discovery strategy used to extract value sets.
_WIDGET_KIND_BY_ATTR: dict[str, str] = {
    "mo.ui.slider": "slider",
    "mo.ui.dropdown": "dropdown",
    "mo.ui.switch": "switch",
    "mo.ui.checkbox": "switch",
    "mo.ui.radio": "radio",
}


@dataclass(frozen=True)
class WidgetCandidate:
    """A statically-discovered precompute candidate.

    ``var_name`` is the assignment target (``slider`` in
    ``slider = mo.ui.slider(...)``). ``values`` is the discovered value
    list, in source order. ``default`` is the value the widget will show
    on first paint (matches marimo's own default-resolution rule:
    explicit ``value=`` kwarg if present, else the first value, else
    None).
    """

    var_name: str
    kind: str  # "slider" | "dropdown" | "switch" | "radio"
    values: list[Any]
    default: Any
    line: int  # 1-indexed source line for error messages


def scan_widgets(source: str) -> list[WidgetCandidate]:
    """Walk a marimo notebook's source and return precompute candidates.

    Skips silently (returns no candidate) for:

    - Continuous-slider patterns (``mo.ui.slider(start, stop)`` with no step)
    - Widget calls assigned to non-name targets (``foo[0] = mo.ui.slider(...)``)
    - Widget calls inside complex expressions (``[mo.ui.slider(...) for ...]``)
    - Widgets with non-literal arguments (``mo.ui.dropdown(options=options)``)

    All of those still RENDER (as static), they just don't precompute.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    out: list[WidgetCandidate] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Assign):
            continue
        # Only handle the simple case ``name = mo.ui.X(...)``. Tuple
        # unpacking, subscripts, attribute assignment etc. are out of scope.
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            continue
        if not isinstance(node.value, ast.Call):
            continue

        attr_path = _dotted_attr(node.value.func)
        if attr_path is None:
            continue
        kind = _WIDGET_KIND_BY_ATTR.get(attr_path)
        if kind is None:
            continue

        candidate = _build_candidate(
            var_name=node.targets[0].id,
            kind=kind,
            call=node.value,
            line=node.lineno,
        )
        if candidate is not None:
            out.append(candidate)
    return out


# --- internals --------------------------------------------------------------


def _dotted_attr(node: ast.AST) -> str | None:
    """Return ``"a.b.c"`` for an attribute/name chain, else None."""
    parts: list[str] = []
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
        return ".".join(reversed(parts))
    return None


def _build_candidate(
    *, var_name: str, kind: str, call: ast.Call, line: int
) -> WidgetCandidate | None:
    """Dispatch to the per-kind value extractor; return a Candidate on success."""
    kwargs = {kw.arg: kw.value for kw in call.keywords if kw.arg is not None}
    if kind == "slider":
        values = _slider_values(call.args, kwargs)
    elif kind == "dropdown":
        values = _dropdown_values(kwargs)
    elif kind == "switch":
        values = [True, False]
    elif kind == "radio":
        values = _list_kwarg(kwargs, "options")
    else:  # pragma: no cover — _WIDGET_KIND_BY_ATTR guards this
        return None

    if values is None:
        return None
    default = _literal_or_none(kwargs.get("value")) if "value" in kwargs else _safe_first(values)
    return WidgetCandidate(var_name=var_name, kind=kind, values=values, default=default, line=line)


def _slider_values(args: list[ast.expr], kwargs: dict[str, ast.expr]) -> list[Any] | None:
    """Slider extraction follows the user-decided rule: opt out continuous
    sliders unless an explicit grid is specified.

    Recognised forms (all with literal numeric arguments):

    - ``mo.ui.slider(steps=[a, b, c, ...])``   — explicit list
    - ``mo.ui.slider(start, stop, step=N)``    — explicit step kwarg
    - ``mo.ui.slider(start, stop, step)``      — three positional args

    Everything else (``mo.ui.slider(start, stop)`` with no step) is
    continuous and skipped.
    """
    if "steps" in kwargs:
        return _list_kwarg(kwargs, "steps")

    # Need start, stop, AND step (positional or kwarg).
    if len(args) >= 3:
        start, stop, step = (
            _literal_or_none(args[0]),
            _literal_or_none(args[1]),
            _literal_or_none(args[2]),
        )
    elif len(args) == 2 and "step" in kwargs:
        start, stop, step = (
            _literal_or_none(args[0]),
            _literal_or_none(args[1]),
            _literal_or_none(kwargs["step"]),
        )
    else:
        return None  # continuous — opt out

    if not all(isinstance(v, (int, float)) for v in (start, stop, step)):
        return None
    if step == 0:
        return None  # malformed

    # Inclusive of stop, like marimo's slider semantics.
    return _arange_inclusive(start, stop, step)


def _arange_inclusive(start: float, stop: float, step: float) -> list[Any]:
    """Numpy-like arange but inclusive of stop, with int coercion when safe."""
    out: list[Any] = []
    n = 0
    while True:
        v = start + n * step
        # Floating-point drift guard: stop iterating once we're past stop
        # by more than half a step in the direction of travel.
        if step > 0 and v > stop + step * 0.5:
            break
        if step < 0 and v < stop + step * 0.5:
            break
        out.append(int(v) if float(v).is_integer() else round(v, 10))
        n += 1
        if n > 10_000:  # safety: never enumerate runaway grids
            break
    return out


def _dropdown_values(kwargs: dict[str, ast.expr]) -> list[Any] | None:
    """Dropdown supports ``options=[...]`` or ``options={k: v, ...}``."""
    raw = kwargs.get("options")
    if raw is None:
        return None
    if isinstance(raw, ast.List):
        out = [_literal_or_none(e) for e in raw.elts]
        zipped = zip(out, raw.elts, strict=True)
        return out if all(o is not None or _is_none_literal(e) for o, e in zipped) else None
    if isinstance(raw, ast.Dict):
        keys = [_literal_or_none(k) for k in raw.keys if k is not None]
        return keys if all(k is not None for k in keys) else None
    return None


def _list_kwarg(kwargs: dict[str, ast.expr], name: str) -> list[Any] | None:
    """Extract a list-literal kwarg as a Python list, or None if non-literal."""
    raw = kwargs.get(name)
    if raw is None or not isinstance(raw, ast.List):
        return None
    out = [_literal_or_none(e) for e in raw.elts]
    if any(o is None and not _is_none_literal(e) for o, e in zip(out, raw.elts, strict=True)):
        return None
    return out


def _literal_or_none(node: ast.expr | None) -> Any:
    """Return the Python value of a literal AST node, or None for non-literals."""
    if node is None:
        return None
    try:
        return ast.literal_eval(node)
    except (ValueError, SyntaxError):
        return None


def _is_none_literal(node: ast.expr) -> bool:
    return isinstance(node, ast.Constant) and node.value is None


def _safe_first(values: list[Any]) -> Any:
    return values[0] if values else None


# --- helpers used by the preprocessor for cap enforcement -------------------


def estimate_combinations(candidates: list[WidgetCandidate]) -> int:
    """Cartesian product size across candidates. Used for cap checks."""
    n = 1
    for c in candidates:
        n *= max(1, len(c.values))
    return n


def page_excluded(book_relative_path: Path | str, exclude_pages: list[str]) -> bool:
    """True iff the book-relative path matches one of ``exclude_pages``."""
    needle = str(book_relative_path).replace("\\", "/")
    return any(needle == ex.replace("\\", "/") for ex in exclude_pages)
