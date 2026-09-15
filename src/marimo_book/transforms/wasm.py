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
The ``@marimo-team/islands`` worker is marimo's regular WASM controller,
so it *does* run ``find_packages()`` + ``micropip.install(missing)`` on
the notebook file it starts — but that file is synthesized in the
browser from the per-cell code (``createMarimoFile`` in
``frontend/src/core/islands/parse.ts``), indented four spaces per line,
with no header. ``find_packages()`` (since marimo dropped import
scanning) only honours a column-zero ``# /// script`` block, which the
synthesized file can never contain, so the install list is always empty.
Pyodide's ``loadPackagesFromImports`` still auto-loads *bundled*
scientific packages (numpy, pandas, scipy, sklearn, matplotlib, nilearn,
nibabel, …) by AST-scanning cell code; anything pure-Python and
PyPI-only (``nltools``, ``dartbrains-tools``) silently fails to import.
Upstream tracking: marimo-team/marimo#9778.

Our workaround rides on the islands JSON payload marimo added in 0.24
(``<script type="application/vnd.marimo.islands+json">``,
marimo-team/marimo#9987). When a payload is present the runtime takes
cell code from it instead of the DOM, and payload cells with no matching
``<marimo-island>`` anchor are still sent to the kernel. So
:func:`build_bootstrap_payload` emits marimo's own payload with two
edits: an extra anchor-less cell that ``await micropip.install([...])``s
the derived dependency list and defines a sentinel variable, and every
user cell's code prefixed with a bare reference to that sentinel so
marimo's dataflow runs the bootstrap first. The staged notebook that
``gen.build()`` executes is never modified for this (the earlier
approach AST-injected the same cell into the source, which round-tripped
every page through ``ast.unparse``). ``with app.setup:`` blocks are
ordinary cells to the islands runtime, so they are covered too.

The preprocessor still stages a copy of the notebook with an
auto-generated PEP 723 block before handing it to
``MarimoIslandGenerator`` — the correct manifest for sandbox mode,
``marimo-book sync-deps`` (molab portability), and the day upstream
carries the block into the runtime file.

Static reactivity (``precompute.enabled``) is automatically a no-op
for WASM-rendered pages: the preprocessor's ``_run_precompute`` is
called only for static-mode entries.

**Anywidget rewrite (the reason this module also imports
:func:`rewrite_anywidget_html`).** Since marimo 0.24
(marimo-team/marimo#10127) a widget's ES module no longer rides on the
``<marimo-anywidget>`` element as ``data-js-url``: it travels on the
kernel's ``ModelOpen`` notification as an ``EsmSpec`` and the islands
generator's session view keeps it per model. :func:`anywidget_esm_by_model`
harvests ``{model_id: js_url}`` from there (under marimo's script runtime
context the URL is already a ``data:text/javascript`` URL) and
:func:`rewrite_anywidget_html` restores ``data-js-url`` on each mount, so
the page's *pre-hydration* paint shows the widget through the same
``marimo_book.js`` shim static pages use.

Once Pyodide boots and the islands runtime re-executes the widget cells,
marimo's own runtime renders the fresh ``<marimo-anywidget>`` elements
itself (widget registry fed by the model notifications; the pre-0.24
"Refusing to load anywidget module from untrusted URL" failure is gone —
verified in a browser with no shim at all). Our mounts are simply replaced
by that repaint, and from then on widget state round-trips to the kernel
natively: cells reading ``widget.value`` see live values. The shim
therefore no longer intercepts runtime-emitted anywidgets (it used to
rewrap them into static mounts, which on 0.24 only blanked a working
widget).
"""

from __future__ import annotations

import ast
import asyncio
import base64
import html as _html
import re
import textwrap
from collections.abc import Sequence
from pathlib import Path

from bs4 import BeautifulSoup
from marimo import MarimoIslandGenerator

# Same private-module rationale as transforms/pep723.py (see the marimo pin
# comment in pyproject.toml): importing the constant and the escaper marimo's
# own render_payload_script() uses means a rename upstream surfaces as an
# ImportError at the pin bump instead of a silently ignored script tag.
from marimo._schemas.islands import ISLANDS_JSON_SCRIPT_TYPE
from marimo._templates import json_script

from .anywidgets import rewrite_anywidget_html
from .author_line import strip_markdown_author_line
from .marimo_export import staged_sibling_file
from .pep723 import BOOTSTRAP_CELL_ID, micropip_bootstrap_code, thread_bootstrap_sentinel

ISLANDS_PAYLOAD_SCRIPT_TYPE = ISLANDS_JSON_SCRIPT_TYPE


def _first_mo_md_constant(tree: ast.AST) -> ast.Constant | None:
    """The string ``Constant`` of the source-earliest ``mo.md("...")`` call."""
    consts = [
        node.args[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "md"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "mo"
        and node.args
        and isinstance(node.args[0], ast.Constant)
        and isinstance(node.args[0].value, str)
    ]
    if not consts:
        return None
    consts.sort(key=lambda c: (c.lineno, c.col_offset))
    return consts[0]


def extract_and_strip_title(source: str) -> tuple[str | None, str]:
    """Pull the page title out of a notebook's first markdown cell.

    On WASM pages the notebook's leading ``# H1`` is emitted *encoded* inside a
    ``<marimo-mime-renderer>`` data attribute, so MkDocs Material can't see a
    literal ``<h1`` in ``page.content`` and injects the nav title as its own
    ``<h1>`` — giving the reader two identical titles. To fix that we hoist the
    title: strip the ``# H1`` line from the first ``mo.md`` cell here (so the
    cell no longer renders it) and let the caller emit one real ``<h1>`` at the
    top of the page body (which Material then detects and leaves alone).

    Works on the AST (the string *value*), not the source text, so it's immune
    to quote style — the WASM staging round-trips the source through
    ``ast.unparse`` (turning ``mo.md(r\"\"\"...\"\"\")`` into a single-quoted
    literal with ``\\n`` escapes), which a source-level regex would miss.

    Returns ``(title, source_without_the_h1_line)``. Returns ``(None, source)``
    unchanged when the first ``mo.md`` cell doesn't begin with an ATX ``# H1``
    (nothing to hoist), so non-title-first notebooks are untouched.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return None, source
    const = _first_mo_md_constant(tree)
    if const is None:
        return None, source
    md = const.value
    first = next((ln for ln in textwrap.dedent(md).splitlines() if ln.strip()), "")
    heading = re.match(r"#[ \t]+(.+?)[ \t]*$", first)
    if not heading:
        return None, source
    title = heading.group(1).strip()
    # Drop the first ATX H1 line (``# ...``) from the markdown value; ``##``+
    # subheadings never match because ``#[ \t]+`` requires whitespace after a
    # single ``#``.
    const.value = re.sub(r"(?m)^[ \t]*#[ \t]+.+\n", "", md, count=1)
    return title, ast.unparse(tree)


def strip_author_line_from_source(source: str) -> str:
    """Drop the byline from the first ``mo.md`` cell of a notebook's source.

    The WASM counterpart of ``hide_author_line``. A body-level strip would not
    hold on these pages: the islands runtime re-renders every cell from the
    payload once Pyodide boots, so the byline has to be gone from the code the
    browser executes. Same AST-level edit as :func:`extract_and_strip_title`,
    and likewise a no-op when the notebook has no byline.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source
    const = _first_mo_md_constant(tree)
    if const is None:
        return source
    stripped = strip_markdown_author_line(const.value)
    if stripped == const.value:
        return source
    const.value = stripped
    return ast.unparse(tree)


def render_wasm_page(
    py_path: Path,
    *,
    display_code: bool = False,
    staged_source_path: Path | None = None,
    timeout: float | None = None,
    packages: Sequence[str] = (),
    hide_author_line: bool = False,
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

    ``packages``: PyPI requirement strings to ``micropip.install`` in the
    browser before any cell runs. When non-empty the page gets an islands
    JSON payload with a bootstrap cell (see :func:`build_bootstrap_payload`);
    when empty no payload is emitted and the runtime parses the DOM as
    before.
    """
    target = staged_source_path or py_path
    source = target.read_text(encoding="utf-8")
    # ``hide_author_line`` has to happen in the source here, not in the body:
    # the islands runtime re-renders every cell from the payload once Pyodide
    # boots, so a body-level strip would reappear (see author_line.py).
    if hide_author_line:
        source = strip_author_line_from_source(source)
    # Hoist the notebook's first ``# H1`` to a real ``<h1>`` at the top of the
    # page (see extract_and_strip_title): otherwise MkDocs Material can't see
    # the islands-encoded heading and injects the nav title, duplicating it.
    title, stripped = extract_and_strip_title(source)
    if not title:
        if source == target.read_text(encoding="utf-8"):
            return _render_wasm_body(
                target,
                display_code=display_code,
                timeout=timeout,
                py_path=py_path,
                packages=packages,
            )
        stripped = source
    with staged_sibling_file(
        target, prefix="marimo_book_title_", content=stripped
    ) as stripped_target:
        body = _render_wasm_body(
            stripped_target,
            display_code=display_code,
            timeout=timeout,
            py_path=py_path,
            packages=packages,
        )
    if not title:
        return body
    return f"<h1>{_html.escape(title)}</h1>\n\n" + body


def _render_wasm_body(
    target: Path,
    *,
    display_code: bool,
    timeout: float | None,
    py_path: Path,
    packages: Sequence[str] = (),
) -> str:
    """Build the islands head + body for ``target`` (see render_wasm_page)."""
    gen = MarimoIslandGenerator.from_file(str(target), display_code=display_code)
    # ``gen.build()`` executes the notebook through marimo's own session
    # machinery (not our ``marimo export`` subprocess), so it doesn't get
    # export_notebook's timeout for free — bound it here so a hung wasm
    # notebook can't stall build/serve/CI.
    try:
        asyncio.run(asyncio.wait_for(gen.build(), timeout))
    except TimeoutError as exc:
        raise RuntimeError(
            f"wasm render timed out after {timeout:g}s for {py_path}. "
            "Raise defaults.execution_timeout in book.yml (or set it to null "
            "to disable) if this notebook legitimately runs longer."
        ) from exc
    head = gen.render_head()
    # ``include_init_island=False`` skips marimo's static "Initializing..."
    # spinner. The bundle is supposed to hide that placeholder once cells
    # render, but the hide-trigger doesn't fire reliably — pages would
    # show a stuck spinner above already-working reactive cells. Cells'
    # static-export initial output already gives the user something to
    # look at during hydration, so dropping the spinner is a clear UX win.
    # ``include_payload`` (marimo >= 0.24, marimo-team/marimo#9987) stays
    # off here: when a page needs the micropip bootstrap we build our own
    # copy of that payload below (build_bootstrap_payload) from the
    # *rewritten* body; pages without PyPI-only deps stay on the DOM-parsing
    # path, which upstream keeps as the supported fallback.
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
    raw_body = body
    body = rewrite_anywidget_html(
        body,
        keep_marimo_controls=True,
        notebook_source=notebook_source,
        esm_by_model=anywidget_esm_by_model(gen),
    )
    if packages:
        # Must come AFTER the anywidget rewrite: the payload copies each
        # island's (rewritten) output HTML so the runtime's materialization
        # writes back exactly what the DOM already shows. Emitted as a plain
        # <script type=...> because that is the shape the islands runtime
        # queries for. Caveat: Material's navigation.instant re-creates
        # inline scripts on page swap and drops the type attribute (the
        # hazard precompute.py dodges with <template>). Harmless today —
        # islands only initialize on a full document load, never on an
        # instant-nav arrival — but if that is ever wired up, this script
        # will need the same treatment.
        payload = build_bootstrap_payload(gen, body, packages, rewritten=body != raw_body)
        body += "\n" + payload_script(payload)
    return head + "\n" + body


def anywidget_esm_by_model(gen: MarimoIslandGenerator) -> dict[str, str]:
    """``{model_id: js_url}`` for every anywidget the islands build created.

    marimo >= 0.24 delivers a widget's ES module on the kernel's ``ModelOpen``
    notification (``EsmSpec.url``) instead of the element; the islands
    generator's session view retains it per model. Under marimo's script
    runtime context virtual files are unsupported, so the URL is already a
    ``data:text/javascript`` URL; a ``/@file/`` URL (should marimo change
    that) is read from the virtual-file store and inlined. Empty when the
    notebook has no anywidgets or before ``gen.build()``.
    """
    from marimo._messaging.notification import ModelOpen

    stubs = getattr(gen, "stubs", ()) or ()
    session_view = next(
        (getattr(s, "_session_view", None) for s in stubs if getattr(s, "_session_view", None)),
        None,
    )
    if session_view is None:
        return {}
    out: dict[str, str] = {}
    for notification in session_view.get_model_notifications():
        message = notification.message
        if not isinstance(message, ModelOpen) or message.esm_spec is None:
            continue
        url = message.esm_spec.url
        if url.startswith(("/@file/", "./@file/")):
            from marimo._runtime.virtual_file import read_virtual_file

            spec = url.split("@file/", 1)[1]
            try:
                byte_length, basename = spec.split("-", 1)
                payload = read_virtual_file(basename, int(byte_length))
            except Exception:  # noqa: BLE001 — unreadable ⇒ widget stays empty, as today
                continue
            url = "data:text/javascript;base64," + base64.b64encode(payload).decode("ascii")
        elif not url.startswith(("data:", "http://", "https://")):
            continue
        out[str(notification.model_id)] = url
    return out


def build_bootstrap_payload(
    gen: MarimoIslandGenerator,
    body_html: str,
    packages: Sequence[str],
    *,
    rewritten: bool = True,
) -> dict:
    """Marimo's islands payload for ``gen`` plus a micropip bootstrap cell.

    Starts from ``gen.render_payload()`` (schema v1: ``schemaVersion``,
    ``appId``, ``cells[{cellId, code, outputHtml, outputMimetype, reactive,
    displayCode, displayOutput}]``) and applies two edits:

    - **A bootstrap cell is prepended** with ``cellId`` =
      :data:`~marimo_book.transforms.pep723.BOOTSTRAP_CELL_ID`, no output,
      ``displayOutput: false``. It has no ``<marimo-island>`` anchor in the
      DOM; the runtime's payload parser only requires that *some* cell of
      the payload matches an anchor, and still puts every payload cell into
      the notebook file it synthesizes for the kernel.
    - **Every reactive cell's code gets the sentinel prefix** (see
      :func:`~marimo_book.transforms.pep723.thread_bootstrap_sentinel`) so
      marimo's dataflow runs the bootstrap before it.

    When ``rewritten`` is true, ``outputHtml`` for anchored cells is taken
    from ``body_html`` (the anywidget-rewritten island markup) rather than
    from marimo's raw output: the runtime overwrites each anchored island's
    ``<marimo-cell-output>`` with the payload's ``outputHtml`` when it
    materializes the payload — which happens once the Pyodide worker is
    ready, i.e. *after* ``marimo_book.js`` has hydrated the page — so the two
    must agree, and the shim re-hydrates on the runtime's
    ``marimo-island-source-changed`` event. When nothing was rewritten the
    payload's own output HTML is already identical and the re-parse is
    skipped.
    """
    payload = dict(gen.render_payload())
    outputs: dict[str, str] = {}
    if rewritten:
        soup = BeautifulSoup(body_html, "html.parser")
        for island in soup.find_all("marimo-island"):
            cell_id = island.get("data-cell-id")
            output = island.find("marimo-cell-output")
            if cell_id and output is not None:
                outputs[str(cell_id)] = output.decode_contents()

    cells = []
    for cell in payload["cells"]:
        cell = dict(cell)
        if cell["cellId"] in outputs:
            cell["outputHtml"] = outputs[cell["cellId"]]
        if cell.get("reactive"):
            cell["code"] = thread_bootstrap_sentinel(cell["code"])
        cells.append(cell)

    bootstrap = {
        "cellId": BOOTSTRAP_CELL_ID,
        "code": micropip_bootstrap_code(packages),
        "outputHtml": "",
        "outputMimetype": "text/plain",
        "reactive": True,
        "displayCode": False,
        "displayOutput": False,
    }
    payload["cells"] = [bootstrap, *cells]
    return payload


def payload_script(payload: dict) -> str:
    """Serialize ``payload`` into the ``<script>`` tag the islands runtime reads.

    Delegates escaping to marimo's ``json_script`` (``<``, ``>``, ``&`` as
    ``\\uXXXX``) — the same helper ``render_payload_script`` uses — so cell
    output HTML inside the JSON can never terminate the script element.
    """
    return f'<script type="{ISLANDS_PAYLOAD_SCRIPT_TYPE}">{json_script(payload)}</script>'
