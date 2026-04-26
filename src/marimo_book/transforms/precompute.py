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

    - ``mo.ui.slider(steps=[a, b, c, ...])``         — explicit list
    - ``mo.ui.slider(start, stop, step=N)``          — start/stop positional, step kwarg
    - ``mo.ui.slider(start, stop, step)``            — three positional args
    - ``mo.ui.slider(start=A, stop=B, step=N)``      — all kwargs (marimo's recommended style)

    Everything else (``mo.ui.slider(start, stop)`` with no step,
    ``mo.ui.slider(start=A, stop=B)`` with no step) is continuous and
    skipped.
    """
    if "steps" in kwargs:
        return _list_kwarg(kwargs, "steps")

    # Resolve start/stop/step from any combination of positional + kwarg.
    # marimo's signature is `slider(start=None, stop=None, step=None, ...)`.
    raw = _resolve_slider_bounds(args, kwargs)
    if raw is None:
        return None  # continuous — opt out
    start, stop, step = raw

    if not all(isinstance(v, (int, float)) for v in (start, stop, step)):
        return None
    if step == 0:
        return None  # malformed

    # Inclusive of stop, like marimo's slider semantics.
    return _arange_inclusive(start, stop, step)


def _resolve_slider_bounds(
    args: list[ast.expr], kwargs: dict[str, ast.expr]
) -> tuple[Any, Any, Any] | None:
    """Return ``(start, stop, step)`` literals from any arg arrangement, or None."""
    # Positional args fill start/stop/step in order.
    positional = [_literal_or_none(a) for a in args[:3]]
    # Kwargs override / fill in the gaps.
    start = positional[0] if len(positional) >= 1 else None
    stop = positional[1] if len(positional) >= 2 else None
    step = positional[2] if len(positional) >= 3 else None
    if "start" in kwargs:
        start = _literal_or_none(kwargs["start"])
    if "stop" in kwargs:
        stop = _literal_or_none(kwargs["stop"])
    if "step" in kwargs:
        step = _literal_or_none(kwargs["step"])
    if start is None or stop is None or step is None:
        return None
    return start, stop, step


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
    """Cartesian product size across candidates.

    Accurate for the joint-precompute case (deferred to a future pass)
    where widgets share downstream cells and need cross-product
    enumeration. For the v1 independent case, use
    :func:`estimate_renders_independent` instead — independent widgets
    cost sum-of-values, not product.
    """
    n = 1
    for c in candidates:
        n *= max(1, len(c.values))
    return n


def estimate_renders_independent(candidates: list[WidgetCandidate]) -> int:
    """Total notebook re-exports needed to precompute N independent widgets.

    Each widget runs once per non-default value (others stay at defaults),
    plus one base render shared across all widgets. So the cost is
    ``1 + sum(values_i - 1)`` not the cartesian product. This is the
    realistic upper bound for v1's independent-widgets pass.
    """
    return 1 + sum(max(0, len(c.values) - 1) for c in candidates)


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
    candidates: list[WidgetCandidate],
    *,
    max_seconds: float,
    max_bytes: int,
    sandbox: bool = False,
) -> PrecomputeResult:
    """Re-export a notebook once per (widget, value), return the staged body.

    Handles 1..N widgets per page. For multiple widgets, each is precomputed
    independently (other widgets stay at their source-defined defaults).
    Downstream cells must be **disjoint** across widgets — joint precompute
    (widgets sharing downstream cells) is deferred to a future pass and
    causes the whole page to render static with a warning.

    Pipeline:

    1. Render the default-value version (also our static fallback).
    2. Project total cost across all widget×value renders; abort if it
       would exceed ``max_seconds``.
    3. For each widget, re-export once per non-default value and diff
       against base; accumulate ``{value_key: {cell_idx: html}}`` table
       and the union of cell indices that changed (its "downstream set").
    4. Verify downstream sets are disjoint across widgets; if any two
       widgets share a downstream cell, fail the whole page.
    5. Wrap each reactive cell with the controlling widget's name; embed
       per-widget metadata + lookup-table script blocks; build per-widget
       input controls.

    Pass a single-element list for the original single-widget case;
    behaviour matches the v0.1.0a5 release.
    """
    t0 = time.monotonic()
    source = py_path.read_text(encoding="utf-8")

    base_export = export_notebook(py_path, sandbox=sandbox)
    base_segments = cells_to_markdown_segments(base_export)
    base_seconds = time.monotonic() - t0
    base_by_idx = {idx: html for idx, html in base_segments}

    static_body = _join_for_page(base_segments)

    total_extra = sum(max(0, len(c.values) - 1) for c in candidates)
    projected = base_seconds * (1 + total_extra)
    if projected > max_seconds:
        return PrecomputeResult(
            body=static_body,
            widget_html="",
            reactive_cell_indices=[],
            seconds_total=base_seconds,
            skipped=True,
            skip_reason=(
                f"projected runtime ({projected:.1f}s × {1 + total_extra} renders) exceeds "
                f"max_seconds_per_page ({max_seconds:.0f}s); rendered static."
            ),
        )

    # Per widget: build deltas + downstream cell set.
    per_widget: list[tuple[WidgetCandidate, dict[str, dict[int, str]], set[int]]] = []
    bytes_so_far = 0
    substitution_failures: list[str] = []  # collected for the result.skip_reason
    for candidate in candidates:
        deltas: dict[str, dict[int, str]] = {}
        downstream: set[int] = set()
        substitution_failed = False
        for value in candidate.values:
            if value == candidate.default:
                continue
            try:
                rewritten = substitute_widget_value(source, candidate, value)
            except WidgetSubstitutionError as exc:
                # Substitution can fail for multi-line calls or other AST
                # surgery edge cases. Record once per widget so the author
                # gets a clear signal instead of silent failure.
                if not substitution_failed:
                    substitution_failures.append(
                        f"{candidate.var_name} (line {candidate.line}): {exc}"
                    )
                    substitution_failed = True
                continue
            try:
                export = export_notebook_with_overrides(
                    py_path, rewritten_source=rewritten, sandbox=sandbox
                )
                segments = cells_to_markdown_segments(export)
            except Exception:  # noqa: BLE001 — keep the build alive on a single bad value
                continue
            delta = {idx: html for idx, html in segments if base_by_idx.get(idx) != html}
            if not delta:
                continue
            deltas[_value_to_key(value)] = delta
            downstream.update(delta)
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
        if downstream:
            per_widget.append((candidate, deltas, downstream))

    if not per_widget:
        # No widget actually affects any cell — render static. Surface
        # substitution failures so the author isn't left guessing.
        skip_reason = None
        if substitution_failures:
            skip_reason = "no widgets could be precomputed; substitution failed for: " + "; ".join(
                substitution_failures
            )
        return PrecomputeResult(
            body=static_body,
            widget_html="",
            reactive_cell_indices=[],
            seconds_total=time.monotonic() - t0,
            skipped=bool(skip_reason),
            skip_reason=skip_reason,
        )

    # Disjointness check across widgets. Joint widgets (shared downstream
    # cells) need cross-product semantics — deferred to a future pass.
    seen: set[int] = set()
    cell_to_widget: dict[int, str] = {}
    for candidate, _, downstream in per_widget:
        overlap = downstream & seen
        if overlap:
            return PrecomputeResult(
                body=static_body,
                widget_html="",
                reactive_cell_indices=[],
                bytes_total=bytes_so_far,
                seconds_total=time.monotonic() - t0,
                skipped=True,
                skip_reason=(
                    f"widgets share downstream cells "
                    f"({sorted(overlap)}); joint multi-widget precompute "
                    f"is deferred. Rendered static."
                ),
            )
        seen.update(downstream)
        for idx in downstream:
            cell_to_widget[idx] = candidate.var_name

    # All disjoint — assemble the staged body.
    body = _join_for_page(_wrap_reactive_segments_multi(base_segments, cell_to_widget))
    body += "\n\n" + "\n".join(
        _embed_metadata(candidate, deltas) for candidate, deltas, _ in per_widget
    )
    widget_html = _build_controls_panel([candidate for candidate, _, _ in per_widget])

    return PrecomputeResult(
        body=body,
        widget_html=widget_html,
        reactive_cell_indices=sorted(seen),
        bytes_total=bytes_so_far,
        seconds_total=time.monotonic() - t0,
    )


# --- internal helpers for the orchestrator --------------------------------


def _join_for_page(segments: list[tuple[int, str]]) -> str:
    """Same whitespace normalisation as cells_to_markdown's joiner."""
    import re

    joined = "\n\n".join(body.strip("\n") for _, body in segments if body.strip())
    return re.sub(r"\n{3,}", "\n\n", joined) + "\n"


def _wrap_reactive_segments_multi(
    segments: list[tuple[int, str]], cell_to_widget: dict[int, str]
) -> list[tuple[int, str]]:
    """Wrap each reactive cell's body, tagged with the widget that drives it.

    The widget tag (``data-precompute-widget="varname"``) lets the JS
    shim limit cell swaps to cells controlled by the changed widget,
    leaving cells controlled by other widgets in their current state.
    """
    out: list[tuple[int, str]] = []
    for idx, body in segments:
        if idx in cell_to_widget:
            wrapped = (
                f'<div class="marimo-book-precompute-cell" '
                f'data-precompute-cell="{idx}" '
                f'data-precompute-widget="{_html_escape(cell_to_widget[idx])}" '
                f'markdown="1">\n\n'
                f"{body}\n\n"
                f"</div>"
            )
            out.append((idx, wrapped))
        else:
            out.append((idx, body))
    return out


def _embed_metadata(candidate: WidgetCandidate, by_value: dict[str, dict[int, str]]) -> str:
    """Emit ``<script type="application/json">`` blocks the JS shim reads.

    Both the widget-metadata block and the lookup-table block carry a
    ``data-precompute-widget="varname"`` attribute so the shim can pair
    them with the matching control on multi-widget pages.
    """
    var_attr = f'data-precompute-widget="{_html_escape(candidate.var_name)}"'
    widget_meta = {
        "var_name": candidate.var_name,
        "kind": candidate.kind,
        "values": [_jsonable(v) for v in candidate.values],
        "default": _jsonable(candidate.default),
    }
    widget_block = (
        f'<script type="application/json" class="marimo-book-precompute-widget" {var_attr}>'
        + json.dumps(widget_meta, separators=(",", ":"))
        + "</script>"
    )
    table_block = (
        f'<script type="application/json" class="marimo-book-precompute-table" {var_attr}>'
        + json.dumps(by_value, separators=(",", ":"))
        + "</script>"
    )
    return widget_block + "\n" + table_block


def _build_controls_panel(candidates: list[WidgetCandidate]) -> str:
    """HTML for the input controls, one mount per widget.

    Each mount is empty — the JS shim discovers it via the
    ``data-precompute-widget`` attribute, locates the matching metadata
    + lookup-table scripts, and renders the appropriate control inside.
    Renders the panel only if there's at least one candidate.
    """
    if not candidates:
        return ""
    mounts = [
        f'<div class="marimo-book-precompute-control" '
        f'data-precompute-widget="{_html_escape(c.var_name)}"></div>'
        for c in candidates
    ]
    return '<div class="marimo-book-precompute-controls">' + "".join(mounts) + "</div>"


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
