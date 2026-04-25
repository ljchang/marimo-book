"""Detect and precompute discrete marimo UI widgets for static reactivity.

This is the **kernel-free reactivity path** for marimo-book's static
render mode (the only render mode in v0.1.x). When v0.2 introduces
WASM / hybrid render modes, those modes will provide native reactivity
in-browser via Pyodide and this whole pipeline will be a no-op for
WASM-rendered pages — gated on ``Book.defaults.mode == "static"`` at
the wire-in point.

The preprocessor calls :func:`scan_widgets` on each marimo notebook's source
to find widget calls whose value set is statically determinable. Candidate
widgets are then driven by ``Preprocessor`` through a per-value re-export
loop (Path X — see the plan); the resulting outputs become a JSON lookup
table embedded in the page, and ``assets/marimo_book.js`` swaps them on
client-side interaction.

This module handles **detection + value substitution**. The actual re-export
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
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .marimo_export import (
    cells_to_markdown_segments,
    export_notebook,
    export_notebook_with_overrides,
)

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


# --- value substitution (Phase 3a) ----------------------------------------


class WidgetSubstitutionError(ValueError):
    """Raised when a widget's source line can't be safely rewritten."""


def substitute_widget_value(source: str, candidate: WidgetCandidate, new_value: Any) -> str:
    """Rewrite ``source`` so ``candidate``'s call gets ``value=new_value``.

    The widget call's ``value=`` kwarg is replaced if it exists, otherwise
    appended. We splice the unparsed call back into the original source
    using AST line/column offsets so the rest of the file (comments,
    decorators, ``__generated_with`` magic) is preserved verbatim.

    Raises ``WidgetSubstitutionError`` for multi-line widget calls (out
    of scope for v1) or when the call at ``candidate.line`` no longer
    matches a recognised widget.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        raise WidgetSubstitutionError(f"source no longer parseable: {exc}") from exc

    target = _find_widget_call_at_line(tree, candidate.line)
    if target is None:
        raise WidgetSubstitutionError(f"no recognised widget call found at line {candidate.line}")

    if target.end_lineno is not None and target.end_lineno != target.lineno:
        raise WidgetSubstitutionError(
            "multi-line widget calls are not supported in v1; "
            "rewrite the widget assignment as a single line"
        )

    value_node = ast.parse(repr(new_value), mode="eval").body
    replaced = False
    for kw in target.keywords:
        if kw.arg == "value":
            kw.value = value_node
            replaced = True
            break
    if not replaced:
        target.keywords.append(ast.keyword(arg="value", value=value_node))

    new_call_src = ast.unparse(target)

    lines = source.split("\n")
    start_line_idx = target.lineno - 1
    line = lines[start_line_idx]
    if target.col_offset is None or target.end_col_offset is None:
        raise WidgetSubstitutionError("AST node missing column offsets")
    rebuilt = line[: target.col_offset] + new_call_src + line[target.end_col_offset :]
    lines[start_line_idx] = rebuilt
    return "\n".join(lines)


def _find_widget_call_at_line(tree: ast.AST, line: int) -> ast.Call | None:
    """Return the ``mo.ui.X(...)`` Call node starting on ``line``, if any."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or node.lineno != line:
            continue
        attr = _dotted_attr(node.func)
        if attr in _WIDGET_KIND_BY_ATTR:
            return node
    return None


# --- per-page orchestration (Phase 3b) ------------------------------------


@dataclass
class PrecomputeResult:
    """Outcome of running precompute on one notebook page.

    The body and ``widget_html`` are what the preprocessor injects into
    the staged page. When ``skipped`` is True (a runtime cap was hit
    after execution started), ``body`` still holds the static-fallback
    render (the default-value version) and ``widget_html`` is empty —
    the page renders normally with no interactivity.
    """

    body: str
    widget_html: str
    reactive_cell_indices: list[int] = field(default_factory=list)
    bytes_total: int = 0
    seconds_total: float = 0.0
    skipped: bool = False
    skip_reason: str | None = None


def precompute_page(
    py_path: Path,
    candidate: WidgetCandidate,
    *,
    max_seconds: float,
    max_bytes: int,
    sandbox: bool = False,
) -> PrecomputeResult:
    """Re-export a notebook once per widget value, return the staged body.

    v1 scope: a single widget per page. The orchestrator:

    1. Renders the default-value version (also our static fallback).
    2. Times the first export and projects the total cost; aborts and
       falls back to static if it would exceed ``max_seconds``.
    3. Re-exports once per non-default value, captures cell-by-cell
       output, and accumulates a ``{value: {cell_idx: html}}`` lookup
       table. Aborts when accumulated bytes would exceed ``max_bytes``.
    4. Wraps cells whose output differs from the base in
       ``<div data-precompute-cell="N">…</div>`` so the JS shim can
       target them, and embeds the lookup table + widget metadata as
       ``<script type="application/json">`` blocks.
    5. Builds the input control HTML for the widget — injected at the
       top of the page by the preprocessor.
    """
    t0 = time.monotonic()
    source = py_path.read_text(encoding="utf-8")

    base_export = export_notebook(py_path, sandbox=sandbox)
    base_segments = cells_to_markdown_segments(base_export)
    base_seconds = time.monotonic() - t0

    static_body = _join_for_page(base_segments)

    n_other = max(0, len(candidate.values) - 1)
    projected = base_seconds * (1 + n_other)
    if projected > max_seconds:
        return PrecomputeResult(
            body=static_body,
            widget_html="",
            reactive_cell_indices=[],
            seconds_total=base_seconds,
            skipped=True,
            skip_reason=(
                f"projected runtime ({projected:.1f}s × {1 + n_other} renders) exceeds "
                f"max_seconds_per_page ({max_seconds:.0f}s); rendered static."
            ),
        )

    base_by_idx = {idx: html for idx, html in base_segments}
    by_value: dict[str, dict[int, str]] = {}
    bytes_so_far = 0

    for value in candidate.values:
        if value == candidate.default:
            continue
        try:
            rewritten = substitute_widget_value(source, candidate, value)
        except WidgetSubstitutionError:
            continue
        try:
            export = export_notebook_with_overrides(
                py_path, rewritten_source=rewritten, sandbox=sandbox
            )
            segments = cells_to_markdown_segments(export)
        except Exception:  # noqa: BLE001 — keep the build alive on a single bad value
            continue

        delta: dict[int, str] = {}
        for idx, html in segments:
            if base_by_idx.get(idx) != html:
                delta[idx] = html
        if not delta:
            continue
        by_value[_value_to_key(value)] = delta
        bytes_so_far += sum(len(v) for v in delta.values())
        if bytes_so_far > max_bytes:
            return PrecomputeResult(
                body=static_body,
                widget_html="",
                reactive_cell_indices=[],
                bytes_total=bytes_so_far,
                seconds_total=time.monotonic() - t0,
                skipped=True,
                skip_reason=(
                    f"lookup table reached {bytes_so_far:,} bytes, exceeding "
                    f"max_bytes_per_page ({max_bytes:,}); rendered static."
                ),
            )

    reactive_indices = sorted({idx for delta in by_value.values() for idx in delta})

    if not reactive_indices:
        # Nothing depends on the widget — render static, no JS needed.
        return PrecomputeResult(
            body=static_body,
            widget_html="",
            reactive_cell_indices=[],
            seconds_total=time.monotonic() - t0,
        )

    body = _join_for_page(_wrap_reactive_segments(base_segments, reactive_indices))
    body += "\n\n" + _embed_metadata(candidate, by_value)
    widget_html = _build_widget_control(candidate)
    return PrecomputeResult(
        body=body,
        widget_html=widget_html,
        reactive_cell_indices=reactive_indices,
        bytes_total=bytes_so_far,
        seconds_total=time.monotonic() - t0,
    )


# --- internal helpers for the orchestrator --------------------------------


def _join_for_page(segments: list[tuple[int, str]]) -> str:
    """Same whitespace normalisation as cells_to_markdown's joiner."""
    import re

    joined = "\n\n".join(body.strip("\n") for _, body in segments if body.strip())
    return re.sub(r"\n{3,}", "\n\n", joined) + "\n"


def _wrap_reactive_segments(
    segments: list[tuple[int, str]], reactive_indices: list[int]
) -> list[tuple[int, str]]:
    """Wrap each reactive cell's body in a JS-targetable div."""
    reactive = set(reactive_indices)
    out: list[tuple[int, str]] = []
    for idx, body in segments:
        if idx in reactive:
            wrapped = (
                f'<div class="marimo-book-precompute-cell" '
                f'data-precompute-cell="{idx}" markdown="1">\n\n'
                f"{body}\n\n"
                f"</div>"
            )
            out.append((idx, wrapped))
        else:
            out.append((idx, body))
    return out


def _embed_metadata(candidate: WidgetCandidate, by_value: dict[str, dict[int, str]]) -> str:
    """Emit ``<script type="application/json">`` blocks the JS shim reads."""
    widget_meta = {
        "var_name": candidate.var_name,
        "kind": candidate.kind,
        "values": [_jsonable(v) for v in candidate.values],
        "default": _jsonable(candidate.default),
    }
    widget_block = (
        '<script type="application/json" class="marimo-book-precompute-widget">'
        + json.dumps(widget_meta, separators=(",", ":"))
        + "</script>"
    )
    table_block = (
        '<script type="application/json" class="marimo-book-precompute-table">'
        + json.dumps(by_value, separators=(",", ":"))
        + "</script>"
    )
    return widget_block + "\n" + table_block


def _build_widget_control(candidate: WidgetCandidate) -> str:
    """HTML for the input control placed at the top of the page.

    The JS shim discovers this element via class, reads the widget
    metadata script, and binds events. We only emit the visible markup
    here — bindings happen at runtime so static viewers (no JS) still
    see a labelled control instead of a broken slider.
    """
    return (
        '<div class="marimo-book-precompute-control" '
        f'data-precompute-var="{_html_escape(candidate.var_name)}">'
        f"</div>"
    )


def _value_to_key(value: Any) -> str:
    """Stable string key for the lookup table.

    Uses ``json.dumps`` so JS-side keys match exactly via ``JSON.stringify``
    on the same value pulled from the widget's ``values`` array. Avoids
    repr-vs-toString cross-language mismatch for floats and booleans.
    """
    return json.dumps(value)


def _jsonable(value: Any) -> Any:
    if isinstance(value, (int, float, bool, str)) or value is None:
        return value
    return str(value)


def _html_escape(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
