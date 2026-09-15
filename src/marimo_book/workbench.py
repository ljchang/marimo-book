"""The in-browser workbench: marimo's editor, self-hosted, with local copies.

A page whose effective ``views`` include ``run`` or ``edit`` gets, besides its
rendered body (the ``read`` view), a *workbench*: marimo's own WASM editor
mounted in a same-origin ``<iframe>`` inside the page's content area. ``run``
opens it in marimo's present view (app-like, nothing is written); ``edit``
opens the full editor. Edits autosave into the reader's browser (IndexedDB)
as a local copy of the published notebook, with a version history, and a
republish is offered as an update rather than applied over their work.

What the build ships for it (all under ``docs/_workbench/``):

``index.html``
    The *mount page* the iframe loads. marimo's own ``_static/index.html``
    with the frozen JSON mount config swapped for ``wb-mount.js``, which
    builds the config as a JavaScript object so it can carry the IndexedDB
    ``fileStores`` entry (a function-bearing object the JSON form can't
    express), and a ``<marimo-wasm>`` marker so the frontend boots Pyodide
    instead of opening a WebSocket. Only marimo's *public* mount surface is
    used (``window.__MARIMO_MOUNT_CONFIG__`` and its ``fileStores`` option,
    marimo-team/marimo#5161).
``assets/``
    A copy of marimo's frontend bundle (~27 MB per marimo version). It must
    be same-origin: the kernel runs in web workers created from
    ``import.meta.url``, and browsers refuse cross-origin worker scripts, so
    a CDN copy would render the editor but never start Python. Copied once
    per build and skipped when the staged copy already matches the installed
    marimo version.
``nb/<toc path>.py``
    The published notebook the workbench boots: the source with the same
    PEP 723 block the rest of the build stages (dependencies install from it
    at boot), hashed so the page can tell a reader's copy is behind.

The page itself gets a small HTML block (:func:`render_workbench_block`)
carrying the per-page data and the shell's markup; ``workbench.js`` (loaded
site-wide, a no-op on pages without the block) mounts the Read/Run/Edit
control in Material's header, swaps the content area between states, and
runs the update banner and history drawer.

Two marimo behaviours the runtime works around, both documented in
``wb-mount.js``: the editor's save flow needs a filename (``notebook.py``) or
Save silently does nothing, and marimo's save worker regenerates the file
from the cells alone, dropping the PEP 723 header and ``marimo.App(...)``
kwargs — the store re-attaches them from the published base on every save
so a reboot still installs the notebook's packages.
"""

from __future__ import annotations

import hashlib
import json
import re
import shutil
from html import escape
from pathlib import Path

from .config import Book, Dependencies, FileEntry
from .transforms.images import page_depth
from .transforms.pep723 import derive_dependencies, write_pep723_block

WORKBENCH_DIR = "_workbench"
"""Subdirectory of ``docs/`` holding the mount page, marimo's assets and notebooks.

Underscore-prefixed so it can never collide with a page: a ``workbench.md``
would otherwise build to the same ``workbench/index.html`` as the mount page.
"""

RUNTIME_FILES = ("wb-store.js", "wb-mount.js")
"""Assets copied next to the mount page (shared IndexedDB layer + mount script)."""

SHELL_JS = "workbench.js"
SHELL_CSS = "workbench.css"

WORKBENCH_BLOCK_END = "<!-- /wb-block -->"
"""Closes the page block; the precompute splice keeps everything up to it."""
WORKBENCH_TAIL_START = "<!-- wb-tail -->"
"""Opens page chrome that follows the body (an assignment card); the splice keeps it."""

_VERSION_MARKER = ".marimo-version"

_MOUNT_CONFIG_RE = re.compile(
    r'<script data-marimo="true">\s*Object\.defineProperty\(window, "__MARIMO_MOUNT_CONFIG__".*?</script>',
    re.S,
)

_ASSETS_ROOT = Path(__file__).parent / "assets" / "workbench"


def workbench_enabled(book: Book) -> bool:
    """Whether any TOC page needs the workbench runtime staged."""
    from .preprocessor import _iter_file_entries  # local: avoid an import cycle

    return any(e.uses_workbench(book.defaults) for e in _iter_file_entries(book.toc))


def marimo_static_dir() -> Path:
    """marimo's bundled frontend (``index.html`` + ``assets/``)."""
    import marimo

    return Path(marimo.__file__).resolve().parent / "_static"


def frontend_config() -> dict:
    """The marimo user config the mount page hands the editor.

    marimo's defaults, with the knobs the workbench relies on pinned:
    autosave after a second of quiet (that is what persists edits), the
    kernel instantiated on boot, and the language-server / Copilot
    integrations off (they have no server to talk to here and only log
    timeouts).
    """
    from marimo._config.config import DEFAULT_CONFIG

    cfg = json.loads(json.dumps(DEFAULT_CONFIG))  # deep copy of a plain dict
    cfg.setdefault("save", {}).update(
        {"autosave": "after_delay", "autosave_delay": 1000, "format_on_save": False}
    )
    cfg.setdefault("runtime", {}).update({"auto_instantiate": True})
    cfg.setdefault("completion", {}).update({"copilot": False})
    cfg.setdefault("language_servers", {}).update({"pylsp": {"enabled": False}})
    return cfg


def mount_page_html(index_html: str, *, marimo_version: str, config: dict) -> str:
    """Turn marimo's ``_static/index.html`` into the workbench mount page."""
    if not _MOUNT_CONFIG_RE.search(index_html):
        raise RuntimeError(
            "marimo's index.html has no __MARIMO_MOUNT_CONFIG__ block; "
            "the installed marimo is newer than the workbench supports"
        )
    html = index_html
    for placeholder, value in (
        ("{{ filename }}", ""),
        ("{{ version }}", marimo_version),
        ("{{ user_config }}", "{}"),
        ("{{ server_token }}", ""),
        ("{{ title }}", "Workbench"),
        ("{{ base_url }}", ""),
    ):
        html = html.replace(placeholder, value)
    boot = (
        "<script>window.__WB__ = "
        + json.dumps({"marimoVersion": marimo_version, "config": config})
        + ";</script>\n"
        '<script src="./wb-store.js"></script>\n'
        '<script src="./wb-mount.js"></script>'
    )
    html = _MOUNT_CONFIG_RE.sub(lambda _m: boot, html, count=1)
    # <marimo-wasm> is how the frontend detects a WASM (Pyodide) page; the
    # styles hide the save button and filename input, which marimo's own
    # html-wasm export hides too — saving is automatic here.
    return html.replace(
        "</head>",
        '<marimo-wasm hidden=""></marimo-wasm>'
        "<style>#save-button,#filename-input{display:none !important}</style></head>",
        1,
    )


def stage_workbench_runtime(
    docs_dir: Path,
    *,
    static_dir: Path | None = None,
    marimo_version: str | None = None,
) -> Path:
    """Stage the mount page, marimo's assets and the runtime scripts.

    Returns the staged ``workbench/`` directory. The (large) assets copy is
    skipped when a previous build already staged the same marimo version.
    """
    if static_dir is None:
        static_dir = marimo_static_dir()
    if marimo_version is None:
        import marimo

        marimo_version = marimo.__version__
    dst = Path(docs_dir) / WORKBENCH_DIR
    dst.mkdir(parents=True, exist_ok=True)

    assets_dst = dst / "assets"
    marker = dst / _VERSION_MARKER
    stale = not marker.exists() or marker.read_text(encoding="utf-8").strip() != marimo_version
    if stale or not assets_dst.exists():
        if assets_dst.exists():
            shutil.rmtree(assets_dst)
        shutil.copytree(static_dir / "assets", assets_dst)
        marker.write_text(marimo_version + "\n", encoding="utf-8")

    index = (static_dir / "index.html").read_text(encoding="utf-8")
    (dst / "index.html").write_text(
        mount_page_html(index, marimo_version=marimo_version, config=frontend_config()),
        encoding="utf-8",
    )
    for name in RUNTIME_FILES:
        shutil.copy(_ASSETS_ROOT / name, dst / name)
    return dst


STORE_JS = "wb-store.js"


def stage_shell_assets(docs_dir: Path) -> None:
    """Copy the page-side shell (JS + CSS) into the standard asset folders.

    The IndexedDB layer is shared with the mount page (both read the same
    database), so it is staged twice: next to the mount page and here.
    """
    docs_dir = Path(docs_dir)
    (docs_dir / "javascripts").mkdir(parents=True, exist_ok=True)
    (docs_dir / "stylesheets").mkdir(parents=True, exist_ok=True)
    shutil.copy(_ASSETS_ROOT / STORE_JS, docs_dir / "javascripts" / STORE_JS)
    shutil.copy(_ASSETS_ROOT / SHELL_JS, docs_dir / "javascripts" / SHELL_JS)
    shutil.copy(_ASSETS_ROOT / SHELL_CSS, docs_dir / "stylesheets" / SHELL_CSS)


def shell_extra_css() -> list[str]:
    return [f"stylesheets/{SHELL_CSS}"]


def shell_extra_javascript(versioned) -> list:
    """``extra_javascript`` entries for the shell; ``versioned`` is shell.py's cache-buster.

    Both deferred, in this order: the store must be defined before the shell runs.
    """
    return [
        {"path": versioned(f"javascripts/{STORE_JS}"), "defer": True},
        {"path": versioned(f"javascripts/{SHELL_JS}"), "defer": True},
    ]


def stage_workbench_notebook(
    src_abs: Path,
    entry_file: Path,
    docs_dir: Path,
    deps_cfg: Dependencies,
    *,
    requires_python: str | None,
) -> tuple[str, str]:
    """Write the published notebook the workbench boots; return ``(url, sha256)``.

    ``url`` is site-root-relative (``_workbench/nb/<toc path>.py``); the page
    block localizes it for the page's depth. The source gets the same PEP
    723 block the rest of the build stages, so the editor installs the same
    packages a WASM page would. The hash is of exactly the bytes written —
    it is what the reader's copy is compared against.
    """
    source = src_abs.read_text(encoding="utf-8")
    deps = derive_dependencies(
        source, extras=deps_cfg.extras, overrides=deps_cfg.overrides, pin=deps_cfg.pin
    )
    published = write_pep723_block(source, deps, requires_python=requires_python)
    rel = Path(WORKBENCH_DIR) / "nb" / Path(entry_file)
    dst = Path(docs_dir) / rel
    dst.parent.mkdir(parents=True, exist_ok=True)
    dst.write_text(published, encoding="utf-8")
    return rel.as_posix(), hashlib.sha256(published.encode("utf-8")).hexdigest()


def render_workbench_block(
    *,
    entry: FileEntry,
    book: Book,
    nb_url: str,
    published_hash: str,
    rel_under_docs: Path,
) -> str:
    """The HTML block a workbench page carries ahead of its rendered body.

    Everything the shell needs rides on ``data-*`` attributes of
    ``#wb-toolbar``; the rest is inert markup (a ``<template>`` for the header
    controls, the update banner, the frame container, the history drawer
    and a toast) that ``workbench.js`` wires up. Pages without this block
    are untouched by the script.
    """
    views = entry.effective_views(book.defaults)
    open_in = entry.effective_open_in(book.defaults)
    prefix = "../" * page_depth(rel_under_docs)
    attrs = {
        "data-nb": Path(entry.file).as_posix(),
        "data-src": prefix + nb_url,
        "data-hash": published_hash,
        "data-views": ",".join(views),
        "data-open-in": open_in,
        "data-wb-root": prefix + WORKBENCH_DIR + "/",
        "data-checkpoint-minutes": str(book.workbench.checkpoint_minutes),
        "data-max-checkpoints": str(book.workbench.max_checkpoints),
    }
    attr_html = " ".join(f'{k}="{escape(v, quote=True)}"' for k, v in attrs.items())
    seg = "".join(
        f'<button class="wb-seg-btn" data-view="{v}" aria-pressed="{str(v == open_in).lower()}">'
        f"{v.capitalize()}</button>"
        for v in views
    )
    # No blank lines inside: Python-Markdown must see one raw HTML block.
    return f"""<div id="wb-block" class="wb-block">
<div id="wb-toolbar" class="wb-toolbar" {attr_html}>
<template id="wb-header-tpl">
<div id="wb-header" class="wb-head">
<span id="wb-status" class="wb-chip" hidden></span>
<div class="wb-seg" role="group" aria-label="Page view">{seg}</div>
<button id="wb-history-btn" class="wb-hbtn" title="Version history of your copy" hidden>History</button>
</div>
</template>
</div>
<div id="wb-banner" class="wb-banner" hidden>
<p id="wb-banner-text"></p>
<span class="wb-grow"></span>
<button id="wb-update" class="wb-btn primary">Update and keep my work</button>
<button id="wb-changes" class="wb-btn">See what changed</button>
<button id="wb-later" class="wb-btn">Not now</button>
</div>
<div id="wb-frame" class="wb-frame" hidden><p id="wb-boot" class="wb-boot"></p></div>
<aside id="wb-history" class="wb-history" hidden aria-label="Version history">
<div class="wb-history-head"><strong id="wb-history-title">Version history</strong><button id="wb-history-close" class="wb-btn">Close</button></div>
<div class="wb-history-save"><input id="wb-note" placeholder="Note for this version (optional)"><button id="wb-save-version" class="wb-btn">Save a version</button></div>
<ol id="wb-history-list" class="wb-history-list"></ol>
<div class="wb-preview">
<div class="wb-preview-head">
<span id="wb-preview-title">Select a version</span>
<span class="wb-grow"></span>
<button id="wb-restore" class="wb-btn primary" hidden>Restore this version…</button>
<button id="wb-restore-confirm" class="wb-btn danger" hidden>Confirm restore</button>
<button id="wb-preview-download" class="wb-btn" hidden>Download</button>
</div>
<pre id="wb-preview"></pre>
</div>
<div class="wb-history-foot">
<button id="wb-reset-btn" class="wb-btn">Reset to published…</button>
<button id="wb-reset-confirm" class="wb-btn danger" hidden>Confirm reset</button>
<button id="wb-forget-btn" class="wb-btn">Delete my copy…</button>
<button id="wb-forget-confirm" class="wb-btn danger" hidden>Confirm delete</button>
</div>
</aside>
<div id="wb-toast" class="wb-toast" hidden><span id="wb-toast-text"></span><button id="wb-toast-action" hidden>Undo</button></div>
</div>
{WORKBENCH_BLOCK_END}"""
