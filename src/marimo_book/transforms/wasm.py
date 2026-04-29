"""WASM rendering via marimo's island runtime.

When a TOC entry's effective mode is ``wasm`` (set via per-entry
``mode: wasm`` in ``book.yml`` or via ``defaults.mode: wasm``), the
preprocessor routes it through this module instead of the static
``cells_to_markdown`` path.

We use marimo's public :class:`MarimoIslandGenerator` API:

1. ``MarimoIslandGenerator.from_file(py_path)`` — loads the notebook
   and registers each cell as an island stub.
2. ``await gen.build()`` — executes the notebook once to capture
   initial state and HTML for each cell.
3. ``gen.render_head()`` — produces ``<script>`` + ``<link>`` tags
   that load marimo's frontend bundle (defaults to jsdelivr CDN; the
   bundle in turn loads Pyodide on first paint to make cells reactive).
4. ``gen.render_body(style="")`` — produces the cell HTML with
   marimo's ``<marimo-island>`` web components.

The head + body are concatenated and embedded in the staged ``.md``.
``style=""`` suppresses marimo's default ``max-width: 740px`` wrapper
so Material's content area controls width.

**Dependency loading in islands (and why PEP 723 alone doesn't fix it).**
``MarimoIslandGenerator`` does not propagate any dependency manifest
into its rendered HTML, and the ``@marimo-team/islands`` worker
bundle has no codepath that reads ``<marimo-code>`` or PEP 723
metadata from the page. The bundle uses two distinct package paths:

- ``pyodide.loadPackagesFromImports(cell_source)`` — auto-loads
  Pyodide-bundled scientific packages (numpy, pandas, scipy, sklearn,
  matplotlib, sympy, nilearn, nibabel, …) by AST-scanning cell code
  for imports. This is how most scientific notebooks "just work".
- ``micropip.install(<hardcoded list>)`` at bootstrap — installs
  marimo itself plus a fixed set (jedi, pygments, docutils,
  pyodide_http, plus pandas/duckdb/sqlglot/pyarrow when ``mo.sql``
  or polars is detected). The list is baked into the JS bundle; no
  path lets a notebook's PEP 723 block extend it.

The result for dartbrains-flavoured pages: any third-party package
that's pure-Python on PyPI but **not** in Pyodide's bundle (the
canonical example being ``nltools``) silently fails to import in the
browser, and there is no add-deps hook in the islands runtime to fix
it from the host page. The fundamental fix requires either switching
this module to ``marimo export html-wasm`` (which DOES read PEP 723)
or upstream changes to the islands runtime.

The preprocessor still stages a copy of the notebook with an
auto-generated PEP 723 block before handing it to
``MarimoIslandGenerator`` — that block is invisible to the islands
runtime today, but it's the correct manifest, useful for sandbox
mode, ``marimo-book sync-deps`` (molab portability), and as the
prerequisite for any future migration to the html-wasm export path.

Static reactivity (``precompute.enabled``) is automatically a no-op
for WASM-rendered pages: the preprocessor's ``_run_precompute`` is
called only for static-mode entries.

**Anywidget rewrite (the reason this module also imports
:func:`rewrite_anywidget_html`).** ``MarimoIslandGenerator`` runs
under marimo's ``ScriptRuntimeContext``, which hardcodes
``virtual_files_supported=False`` — so every anywidget's ES module
gets emitted as a ``data:text/javascript;base64,...`` URL. The
marimo islands runtime then refuses to load those modules
("Refusing to load anywidget module from untrusted URL"); only
``@file/...`` URLs are trusted. Result: anywidgets render as empty
in WASM-mode pages.

We sidestep that by post-processing the islands body with the same
:func:`rewrite_anywidget_html` we use in static mode — rewrapping
``<marimo-anywidget>`` to ``<div class="marimo-book-anywidget">``,
which our ``marimo_book.js`` shim hydrates by importing the data URL
directly. The cells themselves still go through marimo's islands
runtime + Pyodide for full Python reactivity; only the anywidget
modules are mounted by the static shim.

The trade-off: anywidget state set by the shim doesn't round-trip
back to Pyodide (kernel can't see the in-browser model state), so
cells that read ``widget.value`` after the user moves an anywidget
slider see the *initial* value. For widgets driven by ``mo.ui.*``
controls (which DO round-trip via marimo's runtime) full reactivity
is preserved — only "anywidget reading anywidget" patterns are
affected.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

from marimo import MarimoIslandGenerator

from .anywidgets import rewrite_anywidget_html


def render_wasm_page(
    py_path: Path,
    *,
    display_code: bool = False,
    staged_source_path: Path | None = None,
) -> str:
    """Render a marimo notebook as a WASM-interactive page body.

    Returns a single string suitable for splicing into the staged
    ``.md`` page in place of the normal static cell rendering. The
    string contains marimo's head assets (script + style tags) inline
    at the top, followed by the cell HTML — modern browsers tolerate
    ``<script>`` and ``<link>`` in body and execute them in document
    order. Per-page head injection avoids polluting the global
    ``extra_javascript`` list with marimo's bundle on non-WASM pages.

    ``display_code`` toggles whether each cell's source is shown
    alongside its output. The default is False (output only) since
    marimo notebooks typically use ``hide_code=True`` setup cells.

    ``staged_source_path``: when provided, ``MarimoIslandGenerator``
    reads from this path instead of ``py_path``. Used by the
    preprocessor to feed marimo a copy of the notebook with an
    auto-generated PEP 723 inline-metadata block, so the WASM Pyodide
    kernel knows which packages to ``micropip.install`` before any
    cell runs. ``py_path`` is still accepted for backwards
    compatibility and standalone test usage.
    """
    target = staged_source_path or py_path
    gen = MarimoIslandGenerator.from_file(str(target), display_code=display_code)
    asyncio.run(gen.build())
    head = gen.render_head()
    # ``include_init_island=False`` skips marimo's static "Initializing..."
    # spinner. The bundle is supposed to hide that placeholder once cells
    # render, but the hide-trigger doesn't fire reliably — pages would
    # show a stuck spinner above already-working reactive cells. Cells'
    # static-export initial output already gives the user something to
    # look at during hydration, so dropping the spinner is a clear UX win.
    body = gen.render_body(style="", include_init_island=False)
    # Re-target anywidgets to our static-shim mount form. See module docstring
    # for the full rationale; in short, marimo's islands runtime won't load
    # the data: URLs that ScriptRuntimeContext emits for anywidget modules.
    # `keep_marimo_controls=True` because in WASM mode the islands runtime
    # serves <marimo-slider>/<marimo-dropdown>/etc. as live, kernel-backed
    # controls — they must NOT be stripped (only static export does that).
    # `notebook_source` enables the AST-driven `data-driven-by` injection so
    # the shim's rerender() can pull live UIElement values into widget traits.
    notebook_source = target.read_text(encoding="utf-8")
    body = rewrite_anywidget_html(
        body, keep_marimo_controls=True, notebook_source=notebook_source
    )
    return head + "\n" + body
