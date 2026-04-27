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


def render_wasm_page(py_path: Path, *, display_code: bool = False) -> str:
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
    """
    gen = MarimoIslandGenerator.from_file(str(py_path), display_code=display_code)
    asyncio.run(gen.build())
    head = gen.render_head()
    body = gen.render_body(style="")
    # Re-target anywidgets to our static-shim mount form. See module docstring
    # for the full rationale; in short, marimo's islands runtime won't load
    # the data: URLs that ScriptRuntimeContext emits for anywidget modules.
    # `keep_marimo_controls=True` because in WASM mode the islands runtime
    # serves <marimo-slider>/<marimo-dropdown>/etc. as live, kernel-backed
    # controls — they must NOT be stripped (only static export does that).
    body = rewrite_anywidget_html(body, keep_marimo_controls=True)
    return head + "\n" + body
