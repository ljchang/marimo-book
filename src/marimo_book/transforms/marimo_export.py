"""Convert a marimo ``.py`` notebook into a Material-flavored Markdown page.

The pipeline:

1. Run ``marimo export ipynb --include-outputs`` on the source notebook to
   get a standard Jupyter document with rendered cell outputs.
2. Walk the cells and emit a single Markdown string:

   - *Markdown cells* become plain markdown.
   - *Code cells* become fenced ``python`` blocks (optionally hidden when
     the source cell set ``hide_code=True``).
   - *Cell outputs* are translated by output-type: ``text/html`` is embedded
     verbatim (or surgically rewritten when it contains marimo custom
     elements like ``<marimo-callout-output>``); ``text/markdown`` and
     ``text/plain`` are embedded natively; ``image/png`` / ``image/jpeg`` /
     ``image/svg+xml`` are inlined as data URIs.

The resulting Markdown is standalone — no marimo runtime required — and
consumable by Material for MkDocs (or any markdown-native SSG).
"""

from __future__ import annotations

import base64
import html
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

from .anywidgets import contains_anywidget, rewrite_anywidget_html
from .callouts import render_callout_html

# Marimo metadata lives under ``cell.metadata["marimo"]`` in the exported
# notebook. The key names we care about for v0.1:
_HIDE_CODE = "hide_code"


@dataclass
class ExportedNotebook:
    """Parsed view of ``marimo export ipynb --include-outputs``."""

    source: Path
    cells: list[dict]
    metadata: dict


def export_notebook(
    py_path: Path,
    *,
    include_outputs: bool = True,
    sandbox: bool = False,
    suppress_warnings: bool = False,
) -> ExportedNotebook:
    """Run ``marimo export ipynb`` and return the parsed notebook JSON.

    ``sandbox=True`` passes ``--sandbox`` to marimo, which reads the
    notebook's PEP 723 inline metadata and runs the export in an isolated
    ``uv run --isolated`` environment. Requires ``uv`` on PATH.

    ``suppress_warnings=True`` sets ``PYTHONWARNINGS=ignore`` in the export
    subprocess's environment so library warnings don't bleed into cell
    stderr (and from there into the rendered page).
    """
    py_path = Path(py_path)
    cmd = [
        sys.executable,
        "-m",
        "marimo",
        "export",
        "ipynb",
        str(py_path),
        "--force",
    ]
    if include_outputs:
        cmd.append("--include-outputs")
    if sandbox:
        cmd.append("--sandbox")

    env = {**os.environ, "PYTHONWARNINGS": "ignore"} if suppress_warnings else None

    # Route the temp .ipynb through a system temp dir so `marimo-book serve`'s
    # watcher can never see creates/deletes happening in the source tree.
    # Marimo uses the ``.py``'s own path as the working directory for cell
    # execution regardless of where the output file lands, so relative
    # imports inside the notebook still resolve correctly.
    with tempfile.TemporaryDirectory(prefix="marimo_book_") as tmp_dir:
        tmp_out = Path(tmp_dir) / f"{py_path.stem}.ipynb"
        cmd.extend(["-o", str(tmp_out)])
        result = subprocess.run(cmd, capture_output=True, text=True, check=False, env=env)
        # marimo exits non-zero when *some* cells fail to execute but still
        # produces a valid ipynb with error outputs. We accept that case
        # because the preprocessor then emits the error cell visibly.
        stderr = (result.stderr or "").strip()
        if result.returncode != 0 and not tmp_out.exists():
            raise RuntimeError(f"marimo export ipynb failed for {py_path}:\n{stderr[-400:]}")
        nb = json.loads(tmp_out.read_text(encoding="utf-8"))

    return ExportedNotebook(
        source=py_path,
        cells=nb.get("cells", []),
        metadata=nb.get("metadata", {}),
    )


def export_notebook_with_overrides(
    py_path: Path,
    *,
    rewritten_source: str,
    include_outputs: bool = True,
    sandbox: bool = False,
    suppress_warnings: bool = False,
) -> ExportedNotebook:
    """Run ``marimo export`` against ``rewritten_source`` instead of the file.

    Used by the static-reactivity precompute pipeline: it AST-rewrites the
    notebook's source to substitute a widget's ``value=`` (one variant per
    combination), then re-exports to capture cell outputs at that value.

    The rewritten source is written to a temp file inside ``py_path``'s
    parent directory so relative imports resolve identically to the
    original notebook. The temp file's stem matches the original (with a
    suffix) so any user-facing path strings stay intuitive.
    """
    py_path = Path(py_path)
    with tempfile.TemporaryDirectory(
        prefix="marimo_book_precompute_", dir=py_path.parent
    ) as tmp_dir:
        tmp_in = Path(tmp_dir) / py_path.name
        tmp_in.write_text(rewritten_source, encoding="utf-8")
        return export_notebook(
            tmp_in,
            include_outputs=include_outputs,
            sandbox=sandbox,
            suppress_warnings=suppress_warnings,
        )


_ORPHAN_TEMP_PREFIXES: tuple[str, ...] = (
    "marimo_book_precompute_",  # from export_notebook_with_overrides
    "marimo_book_pep723_",  # from preprocessor's PEP 723 staging
)


def cleanup_orphan_precompute_dirs(content_dir: Path) -> int:
    """Remove leaked marimo-book temp dirs in ``content_dir``.

    Sweeps both ``marimo_book_precompute_*`` (from
    :func:`export_notebook_with_overrides`) and ``marimo_book_pep723_*``
    (from the preprocessor's PEP 723 sibling-tempdir staging). These
    are created next to the source notebook so marimo's cell-execution
    cwd resolves relative imports correctly, and removed by their
    ``TemporaryDirectory`` context managers on normal exit. If the
    process is interrupted (Ctrl-C, watcher restart, OOM) the dir
    leaks and pollutes the source tree. Called from the preprocessor
    before each build.

    The function name is preserved for back-compat with callers; the
    sweep covers both prefixes regardless.
    """
    if not content_dir.is_dir():
        return 0
    removed = 0
    for child in content_dir.iterdir():
        if child.is_dir() and child.name.startswith(_ORPHAN_TEMP_PREFIXES):
            shutil.rmtree(child, ignore_errors=True)
            removed += 1
    return removed


def cells_to_markdown(
    exported: ExportedNotebook,
    *,
    hide_first_code_cell: bool = True,
    widget_defaults: dict | None = None,
) -> str:
    """Render the notebook's cells to a single Markdown string.

    ``hide_first_code_cell`` drops the first code cell when it doesn't have
    an output — a common dartbrains-style convention where cell 0 is the
    ``import marimo as mo`` setup. Any marimo notebook whose first cell
    *does* produce an output (rare) keeps it unchanged.
    """
    segments = cells_to_markdown_segments(
        exported,
        hide_first_code_cell=hide_first_code_cell,
        widget_defaults=widget_defaults,
    )
    return _join_segments(segments)


def cells_to_markdown_segments(
    exported: ExportedNotebook,
    *,
    hide_first_code_cell: bool = True,
    widget_defaults: dict | None = None,
) -> list[tuple[int, str]]:
    """Render the notebook into ``(cell_index, body)`` tuples, in order.

    Used by the static-reactivity precompute path so the orchestrator can
    diff individual cells across re-exports. ``cell_index`` is the index
    into ``exported.cells`` (so it survives even if some cells get
    dropped by the hide-first-code-cell rule). The :func:`cells_to_markdown`
    public API joins these into a single Markdown string for the normal
    render path.
    """
    out: list[tuple[int, str]] = []
    first_md_done = False
    first_code_seen = False
    for idx, cell in enumerate(exported.cells):
        if cell.get("cell_type") == "code" and not first_code_seen:
            first_code_seen = True
            if hide_first_code_cell and not cell.get("outputs"):
                continue
        rendered = _render_cell(
            cell,
            first_md_done=first_md_done,
            widget_defaults=widget_defaults,
        )
        if rendered:
            out.append((idx, rendered))
            if cell.get("cell_type") == "markdown":
                first_md_done = True
    return out


def _join_segments(segments: list[tuple[int, str]]) -> str:
    """Same whitespace normalisation as the legacy :func:`cells_to_markdown`."""
    joined = "\n\n".join(body.strip("\n") for _, body in segments if body.strip())
    return re.sub(r"\n{3,}", "\n\n", joined) + "\n"


# --- internal helpers --------------------------------------------------------


def _render_cell(
    cell: dict,
    *,
    first_md_done: bool,
    widget_defaults: dict | None = None,
) -> str | None:
    ct = cell.get("cell_type")
    if ct == "markdown":
        return _render_markdown_cell(cell, strip_duplicate_title=first_md_done)
    if ct == "code":
        return _render_code_cell(cell, widget_defaults=widget_defaults)
    if ct == "raw":
        return _as_str(cell.get("source", ""))
    return None


def _render_markdown_cell(cell: dict, *, strip_duplicate_title: bool) -> str:
    src = _as_str(cell.get("source", "")).strip("\n")
    if not src:
        return ""
    # The plan strips "*Written by …*" attribution lines from the first
    # markdown cell because book.yml already renders authors in the page
    # header. Apply to every markdown cell; the pattern is narrow enough.
    lines = [
        line for line in src.split("\n") if not re.match(r"^\s*\*Written [Bb]y\s+.+\*\s*$", line)
    ]
    return "\n".join(lines).strip("\n")


def _render_code_cell(cell: dict, *, widget_defaults: dict | None = None) -> str:
    src = _as_str(cell.get("source", ""))
    outputs_md = _render_outputs(
        cell.get("outputs", []),
        cell_source=src,
        widget_defaults=widget_defaults,
    )

    hide_code = cell.get("metadata", {}).get("marimo", {}).get("config", {}).get(_HIDE_CODE, False)
    # Cells with hide_code=True AND no meaningful output are noise (typical
    # of the generated import cell). Drop them entirely.
    if hide_code and not outputs_md.strip():
        return ""

    fence = "" if hide_code else f"```python\n{src.rstrip()}\n```"
    if not outputs_md.strip():
        return fence
    if not fence:
        return outputs_md
    return f"{fence}\n\n{outputs_md}"


def _render_outputs(
    outputs: list[dict],
    *,
    cell_source: str = "",
    widget_defaults: dict | None = None,
) -> str:
    rendered: list[str] = []
    for out in outputs:
        text = _render_single_output(out, cell_source=cell_source, widget_defaults=widget_defaults)
        if text:
            rendered.append(text)
    return "\n\n".join(rendered)


def _render_single_output(
    out: dict,
    *,
    cell_source: str = "",
    widget_defaults: dict | None = None,
) -> str:
    ot = out.get("output_type")
    if ot == "stream":
        # stdout/stderr text
        stream_text = _as_str(out.get("text", ""))
        if not stream_text.strip():
            return ""
        return _html_pre(stream_text, extra_class=f"marimo-stream-{out.get('name', 'stdout')}")

    if ot == "error":
        ename = out.get("ename", "Error")
        evalue = out.get("evalue", "")
        tb = "\n".join(_strip_ansi(line) for line in out.get("traceback", []))
        body = f"{ename}: {evalue}\n\n{tb}".strip()
        return _html_pre(body, extra_class="marimo-error")

    if ot in {"display_data", "execute_result"}:
        data = out.get("data", {}) or {}
        return _render_mime_bundle(data, cell_source=cell_source, widget_defaults=widget_defaults)

    return ""


def _render_mime_bundle(
    data: dict,
    *,
    cell_source: str = "",
    widget_defaults: dict | None = None,
) -> str:
    """Pick the richest renderable representation from a MIME bundle."""
    # Priority order: HTML (most expressive) → markdown → images → plain.
    if "text/html" in data:
        return _render_html_output(
            _as_str(data["text/html"]),
            cell_source=cell_source,
            widget_defaults=widget_defaults,
        )
    if "text/markdown" in data:
        md = _as_str(data["text/markdown"]).strip()
        # `marimo export ipynb` sometimes downgrades an anywidget mime
        # bundle to text/markdown with the <marimo-anywidget> tag fully
        # HTML-escaped (`&lt;marimo-anywidget ...`). Detect that and
        # route through the HTML path so the rewriter can mount it.
        # Same trick for any marimo custom element that arrived escaped:
        # <marimo-slider>, <marimo-switch>, etc. Without this, the raw
        # tag leaks into the page as visible escaped text. The HTML path
        # routes through `rewrite_anywidget_html` which strips standalone
        # controls (they have no static analog and are typically replaced
        # by precompute control mounts elsewhere on the page).
        if md.startswith(_ESCAPED_MARIMO_PREFIXES):
            return _render_html_output(
                html.unescape(md),
                cell_source=cell_source,
                widget_defaults=widget_defaults,
            )
        return md
    for mime in ("image/png", "image/jpeg"):
        if mime in data:
            return _render_image(_as_str(data[mime]), mime)
    if "image/svg+xml" in data:
        return _as_str(data["image/svg+xml"])
    if "text/plain" in data:
        text = _as_str(data["text/plain"]).strip()
        if not text:
            return ""
        return _html_pre(text)
    return ""


def _render_html_output(
    raw_html: str,
    *,
    cell_source: str = "",
    widget_defaults: dict | None = None,
) -> str:
    """Translate marimo custom elements to static HTML, pass the rest through."""
    stripped = raw_html.strip()
    if stripped.startswith("<marimo-callout-output"):
        callout = render_callout_html(stripped)
        if callout is not None:
            return callout
    # Rewrap <marimo-anywidget> → <div class="marimo-book-anywidget">, drop
    # standalone UI-control wrappers that have no static analog. Pass the
    # cell's Python source so literal widget kwargs can seed the mount's
    # initial value, plus any book-level widget defaults.
    if contains_anywidget(stripped):
        stripped = rewrite_anywidget_html(
            stripped,
            cell_source=cell_source,
            widget_defaults=widget_defaults,
        ).strip()
        if not stripped:
            return ""
    # Everything else (plain HTML, marimo wrappers we don't recognize yet)
    # passes through untouched. Wrap in a marker div so downstream CSS can
    # style marimo outputs consistently without affecting hand-authored HTML.
    return f'<div class="marimo-book-output">\n{stripped}\n</div>'


def _render_image(payload: str, mime: str) -> str:
    """Inline an image output as a base64 data URI."""
    payload = payload.strip().replace("\n", "")
    # Jupyter stores images as base64 already; re-encode if something sneaks
    # through as raw bytes string.
    if not _looks_like_base64(payload):
        payload = base64.b64encode(payload.encode("utf-8")).decode("ascii")
    return f'<div class="marimo-book-output"><img src="data:{mime};base64,{payload}" /></div>'


def _html_pre(text: str, *, extra_class: str = "") -> str:
    cls = "marimo-book-output-text"
    if extra_class:
        cls = f"{cls} {extra_class}"
    return f'<pre class="{cls}">{html.escape(text)}</pre>'


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(s: str) -> str:
    return _ANSI_RE.sub("", s)


# Marimo custom-element tags that may arrive HTML-escaped under a
# text/markdown mime bundle. We treat any of them as "this is really
# HTML, not markdown" and route through the rewriter (which strips
# standalone controls and rewraps anywidgets). Mirrors
# anywidgets._STANDALONE_CONTROLS plus the marimo-anywidget /
# marimo-ui-element wrappers handled originally.
_ESCAPED_MARIMO_PREFIXES: tuple[str, ...] = (
    "&lt;marimo-anywidget",
    "&lt;marimo-ui-element",
    "&lt;marimo-plotly",
    "&lt;marimo-slider",
    "&lt;marimo-switch",
    "&lt;marimo-dropdown",
    "&lt;marimo-radio",
    "&lt;marimo-number",
    "&lt;marimo-text",
    "&lt;marimo-button",
    "&lt;marimo-checkbox",
    "&lt;marimo-multiselect",
    "&lt;marimo-form",
)


_BASE64_RE = re.compile(r"^[A-Za-z0-9+/=\s]+$")


def _looks_like_base64(s: str) -> bool:
    return bool(_BASE64_RE.match(s))


def _as_str(v) -> str:
    if isinstance(v, list):
        return "".join(v)
    return v or ""
