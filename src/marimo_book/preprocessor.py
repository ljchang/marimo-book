"""Orchestrate a full marimo-book build.

Input: a :class:`~marimo_book.config.Book` plus the root directory that
contains its ``content/`` tree and asset directories.

Output: a staged source tree at ``<out>/docs/`` plus a generated
``<out>/mkdocs.yml``, ready for ``mkdocs build`` (or ``zensical build``) to
consume.

The pipeline intentionally keeps each step small and pure:

- :func:`stage_page` — one TOC entry → one rendered ``.md`` in the staging
  tree.
- :meth:`Preprocessor.build` — walks the TOC, writes pages, copies assets,
  writes ``mkdocs.yml``, writes the default theme CSS / JS.

Nothing here shells out to ``mkdocs`` — that's the CLI's job. A caller can
run the preprocessor standalone and inspect ``_site_src/`` without needing
mkdocs installed.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, datetime
from functools import cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

import yaml

from .api_docs import count_pages, resolve_search_paths, stage_api_docs
from .blog import (
    author_id,
    build_author_roster,
    discover_posts,
    first_heading,
    insert_teaser,
    parse_post_header,
    read_authors_yml,
    render_front_matter,
    resolve_meta,
)
from .config import Book, Dependencies, FileEntry, SectionEntry, UrlEntry
from .launch_buttons import render_button_row
from .rendered_store import RenderedStore
from .shell import _nav_from_toc, emit_mkdocs_yml
from .transforms.citations import _CITE_RE, apply_citations, load_bibliography
from .transforms.link_rewrites import apply_link_rewrites
from .transforms.marimo_export import (
    CellError,
    cells_to_markdown,
    cleanup_orphan_precompute_dirs,
    collect_cell_errors,
    export_notebook,
    staged_sibling_file,
)
from .transforms.pep723 import (
    derive_dependencies,
    has_app_setup_block,
    inject_micropip_bootstrap,
    write_pep723_block,
)
from .transforms.precompute import (
    WidgetCandidate,
    estimate_renders_independent,
    page_excluded,
    precompute_page,
    scan_widgets,
)
from .transforms.wasm import render_wasm_page

# Directories and glob patterns of assets we copy verbatim when present.
_ASSET_DIRS: tuple[str, ...] = ("images", "Code", "data")

# Filename prefix stripped when computing the docs-relative path.
_CONTENT_DIR = "content"


def _first_markdown_heading(markdown: str) -> str | None:
    return first_heading(markdown)


@dataclass
class BuildReport:
    """Summary of what the preprocessor produced."""

    pages: int = 0
    pages_cached: int = 0
    pages_rendered: int = 0
    # Counts of widgets that passed cap checks and would precompute
    # (Phase 2 only previews; Phase 3 wires the actual execution).
    widgets_precomputed: int = 0
    widgets_skipped: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


# --- build cache ------------------------------------------------------------

# Bumped whenever the cache schema or hit-decision rules change.
# v2: entries record ``cell_errors`` so hits can replay the strict/warn verdict.
# v3: entries store the pre-finalize *body* (under ``bodies/``) so hits skip
#     the render AND precompute; buttons/link-rewrites re-apply every build.
_CACHE_SCHEMA_VERSION = 3
_CACHE_DIR_NAME = ".marimo_book_cache"
_CACHE_FILE_NAME = "manifest.json"


class BuildCache:
    """Per-file body cache for ``marimo export`` outputs (schema v3).

    Each ``.py`` TOC entry resolves to a HIT (reuse the cached pre-finalize
    *body* from ``bodies/`` — the finalize step re-applies buttons and link
    rewrites against it every build) or MISS (render fresh, record body +
    fingerprint). Keyed by source content, the marimo-book version, the
    render-only book signature (no TOC/buttons/repo — those are finalize
    inputs), and the entry's effective ``mode``. Precompute output is baked
    into the cached body; its stats and any cell errors are recorded per
    entry and replayed on hits.

    Markdown TOC entries are NOT cached: their render is ~10 ms each and
    not worth the bookkeeping.
    """

    def __init__(self, book_dir: Path, book: Book, *, force_rebuild: bool = False) -> None:
        self.path = book_dir / _CACHE_DIR_NAME / _CACHE_FILE_NAME
        self.bodies_dir = book_dir / _CACHE_DIR_NAME / "bodies"
        self.force_rebuild = force_rebuild
        self.tool_version = _resolve_tool_version()
        self.book_signature = _book_signature(book)
        self.entries: dict[str, dict] = {}
        self.dirty = False
        if not force_rebuild:
            self._load()

    def is_hit(self, src_rel: str, src_abs: Path, *, mode: str) -> bool:
        if self.force_rebuild:
            return False
        entry = self.entries.get(src_rel)
        if entry is None:
            return False
        # The per-entry ``mode:`` override lives in the TOC, which is
        # deliberately NOT part of the cache signature — so a static↔wasm
        # flip must miss here or the wrong-mode body replays forever.
        if entry.get("mode") != mode:
            return False
        # The staged file is rewritten by the finalize step on every build,
        # so a hit is gated on the cached *body* file instead. Verify its
        # content hash too: bodies are written mid-loop while the manifest
        # saves at the end, so an interrupted build can leave a torn or
        # newer-than-manifest body — replaying it silently would publish
        # corrupt output.
        body_file = entry.get("body_file")
        if not body_file:
            return False
        try:
            body_bytes = (self.bodies_dir / body_file).read_bytes()
        except OSError:
            return False
        if hashlib.sha256(body_bytes).hexdigest() != entry.get("body_hash"):
            return False
        try:
            mtime = src_abs.stat().st_mtime
        except OSError:
            return False
        if mtime == entry["src_mtime"]:
            return True
        # mtime moved but content might still match (git checkout, touch,
        # editor that rewrites unchanged files). Fall through to a hash
        # check; refresh the recorded mtime on a content-equal hit so the
        # next build takes the fast path.
        try:
            digest = _file_sha256(src_abs)
        except OSError:
            return False
        if digest != entry["src_hash"]:
            return False
        entry["src_mtime"] = mtime
        self.dirty = True
        return True

    def record(
        self,
        src_rel: str,
        src_abs: Path,
        out_rel: str,
        *,
        body: str,
        apply_rewrites: bool,
        mode: str,
        cell_errors: list[dict] | None = None,
        precompute: dict | None = None,
    ) -> None:
        body_file = Path(src_rel).with_suffix(".md").as_posix()
        body_abs = self.bodies_dir / body_file
        try:
            mtime = src_abs.stat().st_mtime
            digest = _file_sha256(src_abs)
            body_abs.parent.mkdir(parents=True, exist_ok=True)
            body_abs.write_text(body, encoding="utf-8")
        except OSError:
            # Cache bookkeeping must never fail a build whose staged output
            # is already complete (read-only checkout, full disk, …).
            return
        self.entries[src_rel] = {
            "src_mtime": mtime,
            "src_hash": digest,
            "out_path": out_rel,
            "body_file": body_file,
            "body_hash": hashlib.sha256(body.encode("utf-8")).hexdigest(),
            "mode": mode,
            # False for wasm bodies (marimo HTML, not our Markdown) and for
            # precompute-spliced bodies (the splice output was never rewritten).
            "apply_rewrites": apply_rewrites,
            # Raising cells observed at render time, replayed on cache hits —
            # a hit skips the export, and the strict/warn verdict must not
            # depend on whether the page happened to be cached.
            "cell_errors": cell_errors or [],
            # {"widgets", "skipped", "warnings"} recorded at render time and
            # replayed on hits — a hit skips _run_precompute entirely (the
            # spliced output is already baked into the body).
            "precompute": precompute,
            "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.dirty = True

    def body(self, src_rel: str) -> str:
        """The cached pre-finalize body (only valid after an ``is_hit``)."""
        entry = self.entries[src_rel]
        return (self.bodies_dir / entry["body_file"]).read_text(encoding="utf-8")

    def apply_rewrites(self, src_rel: str) -> bool:
        entry = self.entries.get(src_rel) or {}
        return bool(entry.get("apply_rewrites", True))

    def recorded_precompute(self, src_rel: str) -> dict | None:
        entry = self.entries.get(src_rel) or {}
        raw = entry.get("precompute")
        return raw if isinstance(raw, dict) else None

    def recorded_cell_errors(self, src_rel: str) -> list[dict]:
        entry = self.entries.get(src_rel) or {}
        raw = entry.get("cell_errors")
        return raw if isinstance(raw, list) else []

    def save(self) -> None:
        if not self.dirty and self.path.exists():
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": _CACHE_SCHEMA_VERSION,
            "marimo_book_version": self.tool_version,
            "book_yml_hash": self.book_signature,
            "entries": self.entries,
        }
        self.path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self._prune_orphan_bodies()
        self.dirty = False

    def _prune_orphan_bodies(self) -> None:
        """Delete body files no manifest entry references.

        Removed/renamed TOC entries and wholesale invalidations (schema or
        signature change discards the manifest but not the files) would
        otherwise accumulate stale bodies — potentially large, with base64
        images — until ``marimo-book clean``.
        """
        if not self.bodies_dir.exists():
            return
        keep = {(self.bodies_dir / e["body_file"]).resolve() for e in self.entries.values()}
        try:
            for f in sorted(self.bodies_dir.rglob("*"), reverse=True):
                if f.is_file() and f.resolve() not in keep:
                    f.unlink(missing_ok=True)
                elif f.is_dir() and not any(f.iterdir()):
                    f.rmdir()
        except OSError:
            pass  # best-effort hygiene; never fail a build over it

    # --- internals ----------------------------------------------------------

    def _load(self) -> None:
        if not self.path.exists():
            return
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # corrupt cache → silent cold start
        if data.get("version") != _CACHE_SCHEMA_VERSION:
            return
        if data.get("marimo_book_version") != self.tool_version:
            return
        if data.get("book_yml_hash") != self.book_signature:
            return
        loaded = data.get("entries", {})
        if isinstance(loaded, dict):
            self.entries = loaded


def _cell_errors_to_dicts(cell_errors: list[CellError]) -> list[dict]:
    return [{"cell_index": e.cell_index, "ename": e.ename, "evalue": e.evalue} for e in cell_errors]


def _cell_errors_from_dicts(raw: list[dict]) -> list[CellError]:
    return [
        CellError(
            int(d.get("cell_index", 0)), str(d.get("ename", "Error")), str(d.get("evalue", ""))
        )
        for d in raw
        if isinstance(d, dict)
    ]


def _resolve_tool_version() -> str:
    """Read the installed package version; fall back to a sentinel if missing."""
    try:
        return _pkg_version("marimo-book")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def _book_signature(book: Book) -> str:
    """Hash ``book.yml`` fields whose changes invalidate cached *bodies*.

    Composed from :func:`_render_body_signature` (the shared definition of
    "render-affecting config" — keeps the two hashers from drifting apart)
    plus ``precompute``, whose output is baked into the cached body of
    precomputed pages but is irrelevant to ``_rendered/`` (cached mode never
    precomputes).

    Deliberately excludes ``launch_buttons`` / ``repo`` / ``branch`` / the
    TOC — the finalize step (button row + link rewrites) re-runs on every
    build against the cached body, so those edits must NOT re-execute
    notebooks. Per-entry ``mode:`` overrides live in the TOC too; they are
    handled per entry by ``BuildCache.is_hit(mode=...)`` instead.
    """
    relevant: dict = {
        "body": _render_body_signature(book),
        "precompute": book.precompute.model_dump(mode="json"),
    }
    payload = json.dumps(relevant, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


# Bump ONLY when a marimo-book change actually alters a notebook's *rendered
# body* bytes (the export pipeline / cell HTML structure). This is the
# render-output contract version, deliberately decoupled from the package
# version: a release that only touches unrelated surfaces (CLI, nav CSS,
# sync-releases, the button row) must NOT invalidate every committed
# ``_rendered/`` body and force a costly re-execution of heavy notebooks.
# Using the package version here (the old behavior) nuked the cache on every
# release, so a patch bump silently re-executed GPU/video notebooks in CI —
# which, on a deploy runner without the notebooks' deps, published tracebacks.
# "2": WASM pages hoist the notebook's first H1 to a page-level <h1>
# (transforms/wasm.py) — a render-output change, so cached bodies must invalidate.
# "3": that hoist was a no-op on staged (ast.unparse'd) sources until 0.1.30
# made extract_and_strip_title AST-based; bump again so the fixed output lands.
_RENDER_OUTPUT_VERSION = "3"


def _render_body_signature(book: Book) -> str:
    """Hash the fields that change a notebook's *rendered body*.

    Narrower than :func:`_book_signature`: the committed ``_rendered/`` body is
    pre-button and pre-link-rewrite, so it does NOT depend on ``launch_buttons``
    / ``repo`` / ``branch`` / the TOC. It DOES depend on ``defaults``
    (e.g. ``hide_first_code_cell``, ``suppress_warnings``), ``dependencies``
    (which mutate the executed source), ``widget_defaults`` (anywidget seed
    state), and :data:`_RENDER_OUTPUT_VERSION` — a hand-bumped contract version
    that changes only when the export output itself changes, NOT on every
    package release. Stored with each ``RenderedStore`` entry so a build can
    tell a committed body is stale even when the source bytes are unchanged.
    """
    defaults = book.defaults.model_dump(mode="json")
    # execution_timeout can only abort a render, never change its output —
    # including it would mark every committed body stale (and force a costly
    # re-execution of heavy notebooks) each time the knob is tuned or a
    # release adds/renames it. Same rationale as _RENDER_OUTPUT_VERSION.
    defaults.pop("execution_timeout", None)
    relevant: dict = {
        "defaults": defaults,
        "dependencies": book.dependencies.model_dump(mode="json"),
        "widget_defaults": book.widget_defaults,
        "render_output_version": _RENDER_OUTPUT_VERSION,
    }
    payload = json.dumps(relevant, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _splice_precomputed_body(original_page: str, result) -> str:
    """Replace the staged page's body with the precomputed version.

    The original page is ``<launch buttons block>\\n\\n<body>``. We
    preserve the launch-button row verbatim and splice ``result.body``
    (which already contains the cell wrappers + embedded lookup-table
    script blocks) in place of the body.

    The widget control row mounts inline, immediately above the first
    reactive cell — putting the slider next to the content it controls
    instead of stranded at the top of the page. If the body has no
    reactive-cell marker (shouldn't happen for a precomputed page, but
    defensive), we fall back to top-of-body placement.
    """
    return _spliced_page_and_body(original_page, result)[0]


def _spliced_page_and_body(original_page: str, result) -> tuple[str, str]:
    """Like :func:`_splice_precomputed_body` but also returns the body alone.

    The body-only form is what the transient cache stores: replaying it on a
    hit (fresh buttons + verbatim body) reproduces the spliced page without
    re-running a single export.
    """
    # Prefix match — the opening tag carries a data-placement attribute
    # (`<div class="marimo-book-buttons" data-placement="header">`), so an
    # exact `...buttons">` marker never matches and silently dropped the
    # button row from precomputed pages. The row contains no nested <div>,
    # so the first close after the marker is the row's own.
    marker_open = '<div class="marimo-book-buttons"'
    marker_close = "</div>"
    body = _splice_controls_inline(
        result.body, result.widget_html, anchor_cell_idx=result.splice_anchor_cell_idx
    )
    if marker_open in original_page:
        head_end = original_page.index(marker_open)
        close_at = original_page.index(marker_close, head_end) + len(marker_close)
        head = original_page[:close_at]
        return head + "\n\n" + body, body
    return body, body


def _splice_controls_inline(
    body: str, widget_html: str, *, anchor_cell_idx: int | None = None
) -> str:
    """Insert the widget controls inline, immediately above the cell whose
    output the widget drives.

    ``anchor_cell_idx`` is the source-order cell index that consumes the
    widget (computed via AST in :func:`precompute.find_widget_consumer_cell_idx`).
    The cell is identified in the rendered body by its
    ``data-precompute-cell="N"`` wrapper. Mounting at this anchor — the
    cell whose function parameters include the widget variable —
    guarantees the slider lands immediately above the cell whose output
    actually depends on it (the brain viewer, the figure, the table).

    Falls back to the first ``data-precompute-cell`` marker when no
    anchor was identified (rare: notebook with no reactive consumer
    detected via AST). Falls back further to top-of-body when there are
    no reactive markers at all.
    """
    if not widget_html:
        return body
    if anchor_cell_idx is not None:
        needle = (
            f'<div class="marimo-book-precompute-cell" data-precompute-cell="{anchor_cell_idx}"'
        )
        pos = body.find(needle)
        if pos != -1:
            return body[:pos] + widget_html + "\n\n" + body[pos:]
    # Fallback: first reactive cell (legacy behaviour).
    pos = body.find('<div class="marimo-book-precompute-cell"')
    if pos == -1:
        return widget_html + "\n\n" + body
    return body[:pos] + widget_html + "\n\n" + body[pos:]


@contextlib.contextmanager
def _maybe_stage_with_pep723(
    src_abs: Path,
    deps_cfg: Dependencies,
    *,
    enabled: bool,
    wasm_bootstrap: bool = False,
) -> Iterator[Path | None]:
    """Yield a path to a sibling-file copy of ``src_abs`` with PEP 723 injected.

    When ``enabled`` is False, yields ``None`` (callers fall back to the
    original path). When True, walks the notebook's AST, derives the
    dependency list, and writes a copy with a freshly-generated
    ``# /// script`` block to a sibling file in ``src_abs.parent`` (see
    :func:`~marimo_book.transforms.marimo_export.staged_sibling_file`).

    When ``wasm_bootstrap=True`` (set for ``mode: wasm`` pages), also
    AST-injects ``await micropip.install([...])`` into the first
    ``@app.cell`` of the staged copy. Marimo's islands JS bundle has
    no codepath that reads PEP 723 — Pyodide's ``loadPackagesFromImports``
    auto-loads bundled scientific packages by import-scanning, but
    pure-Python PyPI-only deps (the dartbrains-flavoured ``nltools``
    case) silently fail. Shipping the install call inside cell code
    is currently the only way to provision them. See
    :func:`~marimo_book.transforms.pep723.inject_micropip_bootstrap`.

    The staged file lives next to the original notebook (rather than under
    ``.marimo_book_cache/``) so marimo's cell-execution cwd matches the
    original source location — relative imports (``from .util import x``,
    ``open("./data/foo.csv")``) keep resolving as the author intended — and
    so ``Path(__file__).resolve().parent.parent``-style root detection in
    WASM notebooks lands on the real repo root. The staged file is removed
    on context exit; the orphan-sweep at build start handles
    process-interrupted leaks.
    """
    if not enabled:
        yield None
        return

    source = src_abs.read_text(encoding="utf-8")
    deps = derive_dependencies(
        source,
        extras=deps_cfg.extras,
        overrides=deps_cfg.overrides,
        pin=deps_cfg.pin,
    )
    requires_python = deps_cfg.requires_python or _running_python_version_constraint()

    # Order matters: AST-inject the bootstrap FIRST (round-trips through
    # ast.unparse, dropping cell-level comments), then add the PEP 723
    # block via the comment-preserving string-level writer. Doing it the
    # other way around would have ast.unparse strip the just-written
    # block too. Bootstrap fires only when wasm_bootstrap is set AND we
    # have something to install.
    new_source = source
    if wasm_bootstrap and deps:
        # Setup blocks run before any @app.cell, so our sentinel-based
        # ordering can't get the install in first. Pyodide auto-loads
        # *bundled* scientific packages (numpy, pandas, scipy, sklearn,
        # matplotlib, …) via ``loadPackagesFromImports`` during cell
        # parsing, so a setup block whose imports are all bundled works
        # fine. A setup block with any non-bundled import (the
        # dartbrains-tools / nltools class) will fail before our
        # bootstrap can run. We can't tell the two apart cheaply
        # (there's no maintained Pyodide-bundle list in our pipeline),
        # so on detection of any setup block we still inject the
        # bootstrap (covers cells outside the setup block) and emit an
        # advisory warning so the author can audit their setup imports.
        if has_app_setup_block(source):
            print(
                f"  note: {src_abs.name} uses `with app.setup:`. Setup-block "
                "imports run before WASM micropip install; make sure every "
                "import there is in Pyodide's bundled package set, or move "
                "non-bundled imports (nltools, dartbrains-tools, etc.) into "
                "a regular `@app.cell` so the auto-install can run first.",
                file=sys.stderr,
            )
        new_source = inject_micropip_bootstrap(new_source, deps)
    new_source = write_pep723_block(new_source, deps, requires_python=requires_python)

    with staged_sibling_file(src_abs, prefix="marimo_book_pep723_", content=new_source) as staged:
        yield staged


def _running_python_version_constraint() -> str:
    """Default ``requires-python`` when one isn't specified — current ``X.Y``."""
    return f">={sys.version_info.major}.{sys.version_info.minor}"


def _file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return "sha256:" + h.hexdigest()


class Preprocessor:
    """Stateful driver for a single build.

    Constructing the preprocessor does not touch the filesystem; work
    happens in :meth:`build`.
    """

    def __init__(
        self,
        book: Book,
        *,
        book_dir: Path,
        sandbox_override: bool | None = None,
        rebuild: bool = False,
        on_progress: Callable[[str], None] | None = None,
    ) -> None:
        self.book = book
        self.book_dir = Path(book_dir).resolve()
        # None = honour book.yml's dependencies.mode; True/False overrides.
        self.sandbox_override = sandbox_override
        # Called with a human-readable line before/after slow per-entry work
        # (notebook exports take seconds-to-minutes; without this, build and
        # serve look hung). None = silent.
        self.on_progress = on_progress
        # When True, every TOC entry is re-rendered regardless of cache state.
        # The cache is still updated so future builds without --rebuild benefit.
        self.rebuild = rebuild
        # Signature of render-affecting config + tool version, stored with each
        # committed ``_rendered/`` body so a stale artifact is detected even
        # when the notebook source bytes are unchanged.
        self.body_signature = _render_body_signature(book)

    @property
    def sandbox(self) -> bool:
        """Effective sandbox setting for this build."""
        if self.sandbox_override is not None:
            return self.sandbox_override
        return self.book.dependencies.mode == "sandbox"

    def _progress(self, message: str) -> None:
        if self.on_progress is not None:
            self.on_progress(message)

    def _apply_cell_error_policy(
        self,
        entry: FileEntry,
        cell_errors: list[CellError],
        report: BuildReport,
        *,
        strict: bool,
        note: str,
    ) -> None:
        """Route a page's raising cells to the report.

        ``strict`` makes them build failures; otherwise they are warnings
        suffixed with ``note`` (what the visible traceback ends up in).
        ``allow_errors: true`` on the entry silences both — for pages that
        intentionally demonstrate exceptions.
        """
        if not cell_errors or entry.allow_errors:
            return
        sink = report.errors if strict else report.warnings
        for e in cell_errors:
            sink.append(
                f"{entry.file}: code cell {e.cell_index} raised {e.ename}: {e.evalue}"
                + ("" if strict else f" ({note})")
            )

    # --- public API ----------------------------------------------------------

    def build(
        self, *, out_dir: Path, site_dir: Path | None = None, strict: bool = False
    ) -> BuildReport:
        """Stage ``docs/`` and emit ``mkdocs.yml`` under ``out_dir``.

        ``site_dir`` is where ``mkdocs build`` will later emit the finished
        HTML. It defaults to a sibling of ``out_dir`` called ``_site``.

        With ``strict=True`` a stale or missing ``mode: cached`` artifact is a
        hard error (``report.errors``) with no live-render fallback — so a CI
        build never silently re-executes a notebook the author forgot to
        ``marimo-book render``. Without it, the stale path warns and falls back
        to a live render so local authoring still works.
        """
        out_dir = Path(out_dir).resolve()
        docs_dir = out_dir / "docs"
        if site_dir is None:
            site_dir = out_dir.parent / "_site"
        else:
            site_dir = Path(site_dir).resolve()

        # Stage into the existing docs tree in place — critical for
        # ``marimo-book serve``: mkdocs's livereload tracks individual file
        # mtimes, and wholesale rmtree + recreate was making it miss
        # updates. Stale files from a previous build (entries removed from
        # the TOC) will linger; users should ``marimo-book clean`` to start
        # fresh, or rely on ``build --clean`` when cutting a release.
        docs_dir.mkdir(parents=True, exist_ok=True)

        report = BuildReport()

        self._stage_assets(docs_dir, report)
        self._write_defaults(docs_dir)
        extra_css = self._stage_extra_css(docs_dir, report)

        file_entries = _iter_file_entries(self.book.toc)

        # The first TOC entry becomes the site's home page (rendered to
        # docs/index.md). Without this, the header logo's "/" link 404s
        # because mkdocs only treats files literally named index.md as
        # the site root.
        index_source = Path(file_entries[0].file) if file_entries else None

        # Sweep orphan precompute temp dirs from previous interrupted runs
        # (Ctrl-C, watcher restart, OOM). They live alongside the notebook
        # so the precompute pipeline can resolve sibling-module imports;
        # the trade-off is they leak when the marimo subprocess is killed.
        for content_dir in {(self.book_dir / e.file).parent for e in file_entries}:
            cleanup_orphan_precompute_dirs(content_dir)
        md_basenames = {
            _doc_relpath_for(e.file, index_source=index_source).with_suffix("").name
            for e in file_entries
        }

        cache = BuildCache(self.book_dir, self.book, force_rebuild=self.rebuild)
        rendered_store = RenderedStore(self.book_dir)

        # Progress lines cover only .py entries — Markdown stages in ~10 ms,
        # notebooks in seconds-to-minutes.
        py_total = sum(1 for e in file_entries if e.file.suffix == ".py")
        py_seen = 0

        for entry in file_entries:
            src_rel = str(entry.file)
            src_abs = (self.book_dir / entry.file).resolve()
            out_rel = _doc_relpath_for(entry.file, index_source=index_source).as_posix()
            mode = entry.effective_mode(self.book.defaults.mode)
            if entry.file.suffix == ".py":
                py_seen += 1
            tag = f"[{py_seen}/{py_total}]"
            try:
                # mode=cached: source outputs from the committed _rendered/
                # artifact instead of executing the notebook. Never touches the
                # transient cache or precompute (the committed body is final).
                if entry.file.suffix == ".py" and mode == "cached":
                    self._progress(f"{tag} {src_rel} (committed render)")
                    self._stage_cached(
                        entry,
                        src_rel,
                        src_abs,
                        docs_dir,
                        rendered_store,
                        md_basenames=md_basenames,
                        index_source=index_source,
                        report=report,
                        strict=strict,
                    )
                    report.pages += 1
                    continue

                # Notebook entries are the only ones worth caching: marimo
                # export takes seconds-to-minutes, vs ~10 ms for Markdown.
                if entry.file.suffix == ".py" and cache.is_hit(src_rel, src_abs, mode=mode):
                    self._progress(f"{tag} {src_rel} (cache hit)")
                    # Replay cell errors recorded at render time — a hit skips
                    # the export entirely, so without this a page that failed
                    # `--strict` once would pass on the very next (cached) run.
                    self._apply_cell_error_policy(
                        entry,
                        _cell_errors_from_dicts(cache.recorded_cell_errors(src_rel)),
                        report,
                        strict=strict,
                        note="traceback published to page",
                    )
                    # Re-finalize the cached body with THIS build's TOC and
                    # button context — that's what lets the cache key ignore
                    # TOC/repo/button edits. Precompute output is already
                    # baked into the body; replay its stats and skip the grid.
                    _finalize_page(
                        self.book,
                        self.book_dir,
                        entry,
                        docs_dir,
                        cache.body(src_rel),
                        apply_rewrites=cache.apply_rewrites(src_rel),
                        md_basenames=md_basenames,
                        index_source=index_source,
                    )
                    self._apply_precompute_stats(report, cache.recorded_precompute(src_rel))
                    report.pages_cached += 1
                else:
                    if entry.file.suffix == ".py":
                        self._progress(f"{tag} rendering {src_rel}...")

                    # A raising cell renders its traceback into the page (a
                    # deliberate authoring aid) but must not slip through CI:
                    # strict makes it a build failure, non-strict a warning.
                    # Collected (not routed) here so the raw list can also be
                    # recorded in the cache for replay on future hits.
                    collected_errors: list[CellError] = []
                    staged = stage_page(
                        self.book,
                        self.book_dir,
                        entry,
                        docs_dir,
                        md_basenames=md_basenames,
                        sandbox=self.sandbox,
                        index_source=index_source,
                        on_cell_errors=collected_errors.extend,
                    )
                    self._apply_cell_error_policy(
                        entry,
                        collected_errors,
                        report,
                        strict=strict,
                        note="traceback published to page",
                    )

                    # Static-reactivity precompute: scan widgets, apply caps,
                    # re-export per value, splice the lookup table into the
                    # staged page so the JS shim can swap reactive cells. WASM
                    # pages get native reactivity from marimo's runtime in the
                    # browser, so precompute is a no-op for them. Only fresh
                    # renders reach here — hits replay the recorded result.
                    cached_body, cached_rewrites = staged.body, staged.apply_rewrites
                    precompute_stats: dict | None = None
                    if (
                        entry.file.suffix == ".py"
                        and self.book.precompute.enabled
                        and entry.effective_mode(self.book.defaults.mode) == "static"
                    ):
                        spliced_body, precompute_stats = self._run_precompute(
                            entry, src_abs, docs_dir, index_source=index_source
                        )
                        if (
                            spliced_body is not None
                            and self.book.bibliography.files
                            and _CITE_RE.search(spliced_body)
                        ):
                            # Citations don't (yet) apply to precompute-spliced
                            # bodies — the splice output can't go through the
                            # rewrite pipeline. Warn via the stats so cache-hit
                            # replays repeat the warning too.
                            precompute_stats.setdefault("warnings", []).append(
                                f"{entry.file}: citations are not rendered on "
                                f"precomputed pages ([@key] left verbatim)"
                            )
                        self._apply_precompute_stats(report, precompute_stats)
                        if spliced_body is not None:
                            # The splice replaced the page body wholesale;
                            # replaying it verbatim (no rewrites) reproduces
                            # today's staged bytes on a future hit. Link
                            # rewrites have never applied to spliced bodies
                            # (pre-existing: the splice replaces the rewritten
                            # body with a fresh unrewritten export) — fixing
                            # that belongs in _run_precompute, not here.
                            cached_body, cached_rewrites = spliced_body, False

                    # A transient precompute skip (runtime cap on a loaded
                    # machine) must not be frozen into the cache as a static
                    # page — leave the entry unrecorded so the next build
                    # retries the widget grid.
                    transient_skip = bool(precompute_stats and precompute_stats.get("transient"))
                    if entry.file.suffix == ".py" and not transient_skip:
                        cache.record(
                            src_rel,
                            src_abs,
                            out_rel,
                            body=cached_body,
                            apply_rewrites=cached_rewrites,
                            mode=mode,
                            cell_errors=_cell_errors_to_dicts(collected_errors),
                            precompute=precompute_stats,
                        )
                    report.pages_rendered += 1
                report.pages += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{entry.file}: {exc.__class__.__name__}: {exc}")

        cache.save()

        nav = _nav_from_toc(self.book.toc)
        if self.book.include_changelog and self._stage_changelog(docs_dir):
            nav.append({"Changelog": "changelog.md"})
            report.pages += 1

        self._stage_blog(docs_dir, report)
        if self.book.blog.enabled:
            nav.append({self.book.blog.title: f"{self.book.blog.dir}/index.md"})

        # Absolute source-search dirs handed to the mkdocstrings plugin;
        # stays empty when no api_docs.paths are configured (import-only).
        api_paths: list[str] = []
        if self.book.api_docs.enabled:
            resolved = resolve_search_paths(self.book.api_docs, self.book_dir)
            api_paths = [str(p) for p in resolved]
            api_nav = stage_api_docs(self.book.api_docs, search_paths=resolved, docs_dir=docs_dir)
            nav.extend(api_nav)
            report.pages += count_pages(api_nav)

        emit_mkdocs_yml(
            self.book,
            docs_dir=docs_dir.relative_to(out_dir),
            site_dir=site_dir,
            out_path=out_dir / "mkdocs.yml",
            nav=nav,
            extra_css=extra_css or None,
            api_paths=api_paths or None,
        )

        return report

    def render_cached(self, *, check_only: bool = False) -> BuildReport:
        """Regenerate (and commit) ``_rendered/`` for every ``mode: cached`` page.

        This is what ``marimo-book render`` runs — on the author's machine, with
        the notebook's real dependencies — so that CI can later build without
        executing anything. With ``check_only=True`` nothing is written; pages
        whose committed output is stale/missing land in ``report.warnings`` (for
        a CI ``--check`` gate).
        """
        report = BuildReport()
        store = RenderedStore(self.book_dir)
        default_mode = self.book.defaults.mode
        targets = [
            e
            for e in _iter_file_entries(self.book.toc)
            if e.file.suffix == ".py" and e.effective_mode(default_mode) == "cached"
        ]
        for pos, entry in enumerate(targets, 1):
            src_rel = str(entry.file)
            src_abs = (self.book_dir / entry.file).resolve()
            report.pages += 1
            if check_only:
                if store.is_fresh(src_rel, src_abs, body_sig=self.body_signature):
                    report.pages_cached += 1
                else:
                    report.warnings.append(
                        f"{entry.file}: "
                        f"{store.reason_stale(src_rel, src_abs, body_sig=self.body_signature)}"
                    )
                continue
            try:
                # These are the notebooks documented to run for hours on a
                # GPU box — say which one is executing and how many remain.
                self._progress(f"[{pos}/{len(targets)}] rendering {src_rel}...")
                # ``render`` runs on the author's machine — a raising cell
                # would otherwise be committed to ``_rendered/`` unnoticed.
                # Warn (not error): a demo-exception page is legitimate and
                # ``allow_errors: true`` silences it entirely. The raw list is
                # also stored with the artifact so a later ``build --strict``
                # can fail on the committed traceback without executing.
                collected_errors: list[CellError] = []
                body = render_py_body(
                    self.book,
                    self.book_dir,
                    entry,
                    sandbox=self.sandbox,
                    on_cell_errors=collected_errors.extend,
                )
                self._apply_cell_error_policy(
                    entry,
                    collected_errors,
                    report,
                    strict=False,
                    note="traceback committed to _rendered/",
                )
                store.write(
                    src_rel,
                    src_abs,
                    body,
                    body_sig=self.body_signature,
                    cell_errors=_cell_errors_to_dicts(collected_errors),
                )
                report.pages_rendered += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{entry.file}: {exc.__class__.__name__}: {exc}")
        if not check_only:
            store.save()
        return report

    # --- internals -----------------------------------------------------------

    def _stage_cached(
        self,
        entry: FileEntry,
        src_rel: str,
        src_abs: Path,
        docs_dir: Path,
        store: RenderedStore,
        *,
        md_basenames: set[str],
        index_source: Path | None,
        report: BuildReport,
        strict: bool = False,
    ) -> None:
        """Stage a ``mode: cached`` page from the committed ``_rendered/`` body.

        On a fresh committed artifact, no notebook executes. On a stale/missing
        one: under ``strict`` it is a hard error with no execution (the CI
        guarantee); otherwise it warns and falls back to a live render so local
        authoring still works.
        """
        if store.is_fresh(src_rel, src_abs, body_sig=self.body_signature):
            # The committed body may contain tracebacks captured at render
            # time; replay them so the strict gate applies to cached pages
            # the same as to freshly executed ones.
            self._apply_cell_error_policy(
                entry,
                _cell_errors_from_dicts(store.recorded_cell_errors(src_rel)),
                report,
                strict=strict,
                note="traceback committed to _rendered/",
            )
            _finalize_page(
                self.book,
                self.book_dir,
                entry,
                docs_dir,
                store.read_body(src_rel),
                apply_rewrites=True,
                md_basenames=md_basenames,
                index_source=index_source,
            )
            report.pages_cached += 1
            return

        reason = store.reason_stale(src_rel, src_abs, body_sig=self.body_signature)
        if strict:
            # CI / release build: never execute a notebook the author forgot to
            # render. Fail loudly instead of falling back to a live render.
            report.errors.append(
                f"{entry.file}: mode=cached but {reason}; refusing to execute "
                f"under --strict. Run `marimo-book render` and commit _rendered/."
            )
            return

        report.warnings.append(
            f"{entry.file}: mode=cached but {reason}; "
            f"rendering fresh (executes). Run `marimo-book render` and commit "
            f"_rendered/ so CI need not execute."
        )
        collected_errors: list[CellError] = []
        stage_page(
            self.book,
            self.book_dir,
            entry,
            docs_dir,
            md_basenames=md_basenames,
            sandbox=self.sandbox,
            index_source=index_source,
            on_cell_errors=collected_errors.extend,
        )
        self._apply_cell_error_policy(
            entry,
            collected_errors,
            report,
            strict=False,  # this branch is only reachable when strict is off
            note="traceback published to page",
        )
        report.pages_rendered += 1

    def _stage_assets(self, docs_dir: Path, report: BuildReport) -> None:
        for name in _ASSET_DIRS:
            src = self.book_dir / name
            if not src.exists():
                continue
            dst = docs_dir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
        # Copy a top-level CNAME file (single line: the apex domain) if the
        # author supplied one. mkdocs treats unknown files in docs_dir as
        # static assets and ships them to site_dir, so GitHub Pages keeps
        # the custom-domain setting on every redeploy.
        cname_src = self.book_dir / "CNAME"
        if cname_src.exists() and cname_src.is_file():
            shutil.copy2(cname_src, docs_dir / "CNAME")

    def _apply_precompute_stats(self, report: BuildReport, stats: dict | None) -> None:
        """Fold precompute counters/warnings into the report.

        One code path for fresh runs AND cache-hit replays, so the report
        reads identically whether the widget grid executed or was reused.
        """
        if not stats:
            return
        report.widgets_precomputed += stats.get("widgets", 0)
        report.widgets_skipped += stats.get("skipped", 0)
        report.warnings.extend(stats.get("warnings", []))

    def _run_precompute(
        self,
        entry: FileEntry,
        src_abs: Path,
        docs_dir: Path,
        index_source: Path | None = None,
    ) -> tuple[str | None, dict | None]:
        """Detect widget candidates, apply caps, run the per-value re-export.

        Handles 1..N widgets per page. Each widget is precomputed
        independently; when widgets have disjoint downstream cells they
        coexist on one page. Joint widgets (sharing a downstream cell)
        still cause the page to render static — that's the next pass.

        Returns ``(spliced_body, stats)``: the body-only spliced content when
        the page precomputed (``None`` when it stayed static), plus counter/
        warning stats for :meth:`_apply_precompute_stats`. Nothing is written
        to the report here — the caller applies stats, and also records them
        in the cache so hits can replay the identical report lines.
        """
        cfg = self.book.precompute
        if page_excluded(entry.file, cfg.exclude_pages):
            return None, None

        try:
            source = src_abs.read_text(encoding="utf-8")
        except OSError:
            return None, None
        candidates = scan_widgets(source)
        if not candidates:
            return None, None

        # Per-widget count cap (cheap pre-check before any execution).
        kept: list[WidgetCandidate] = []
        warnings: list[str] = []
        skipped = 0
        for c in candidates:
            if len(c.values) > cfg.max_values_per_widget:
                warnings.append(
                    f"{entry.file}:{c.line} {c.var_name} "
                    f"({len(c.values)} values) exceeds "
                    f"max_values_per_widget ({cfg.max_values_per_widget}); "
                    f"rendered static."
                )
                skipped += 1
                continue
            kept.append(c)
        if not kept:
            return None, {"widgets": 0, "skipped": skipped, "warnings": warnings}

        # Page-wide cap. For v1 (independent widgets), realistic cost
        # is ``1 + sum(values_i - 1)`` — sum, not cartesian product —
        # because each widget runs independently with others at default.
        # The legacy ``max_combinations_per_page`` name still fits the
        # joint-cross-product case (deferred), and we use it as the bound
        # on total renders here.
        renders = estimate_renders_independent(kept)
        if renders > cfg.max_combinations_per_page:
            warnings.append(
                f"{entry.file}: precompute would need {renders} re-exports across "
                f"{len(kept)} widgets, exceeding max_combinations_per_page "
                f"({cfg.max_combinations_per_page}); rendered static."
            )
            return None, {"widgets": 0, "skipped": skipped + len(kept), "warnings": warnings}

        result = precompute_page(
            src_abs,
            kept,
            max_seconds=float(cfg.max_seconds_per_page),
            max_bytes=cfg.max_bytes_per_page,
            max_combinations=cfg.max_combinations_per_page,
            sandbox=self.sandbox,
            suppress_warnings=self.book.defaults.suppress_warnings,
            timeout=self.book.defaults.execution_timeout,
        )
        if result.skipped:
            # Runtime caps (time/bytes projections) depend on machine load —
            # mark the skip transient so the caller does NOT cache the page
            # as static forever; the next build retries the grid.
            warnings.append(f"{entry.file}: {result.skip_reason}")
            return None, {
                "widgets": 0,
                "skipped": skipped + len(kept),
                "warnings": warnings,
                "transient": True,
            }
        if not result.reactive_cell_indices:
            # Widgets exist but no downstream cells changed; static is fine.
            return None, {"widgets": 0, "skipped": skipped, "warnings": warnings}

        out_rel = _doc_relpath_for(entry.file, index_source=index_source)
        staged_path = docs_dir / out_rel
        if not staged_path.exists():
            return None, {"widgets": 0, "skipped": skipped, "warnings": warnings}
        original = staged_path.read_text(encoding="utf-8")
        page, spliced_body = _spliced_page_and_body(original, result)
        staged_path.write_text(page, encoding="utf-8")
        return spliced_body, {"widgets": len(kept), "skipped": skipped, "warnings": warnings}

    def _stage_changelog(self, docs_dir: Path) -> bool:
        """Copy ``CHANGELOG.md`` into the staged tree.

        Looks first at ``book_dir/CHANGELOG.md`` (the typical single-dir
        book layout) and falls back to ``book_dir.parent/CHANGELOG.md``
        (the common case where the docs site lives in a ``docs/`` subdir
        of a repo whose CHANGELOG sits at the repo root).

        Returns ``True`` if a changelog was staged, ``False`` if neither
        location has one — silent no-op so the flag is safe to leave on.
        """
        for candidate in (
            self.book_dir / "CHANGELOG.md",
            self.book_dir.parent / "CHANGELOG.md",
        ):
            if candidate.exists():
                (docs_dir / "changelog.md").write_text(
                    candidate.read_text(encoding="utf-8"), encoding="utf-8"
                )
                return True
        return False

    def _render_notebook_body(
        self, src: Path, on_cell_errors: Callable[[list[CellError]], None] | None = None
    ) -> str:
        """Render a .py blog post to static markdown (reuses the page path)."""
        needs_pep723 = self.book.dependencies.auto_pep723
        with _maybe_stage_with_pep723(
            src, self.book.dependencies, enabled=needs_pep723, wasm_bootstrap=False
        ) as staged:
            return _render_marimo(
                staged or src, self.book, sandbox=False, on_cell_errors=on_cell_errors
            )

    def _stage_blog(self, docs_dir: Path, report: BuildReport) -> None:
        """Render and stage blog posts + index + merged .authors.yml."""
        if not self.book.blog.enabled:
            return
        blog_src = self.book_dir / self.book.blog.dir
        posts = discover_posts(blog_src)
        out_blog = docs_dir / self.book.blog.dir
        out_posts = out_blog / "posts"
        out_posts.mkdir(parents=True, exist_ok=True)

        default_author = self.book.blog.default_author
        if default_author is None and len(self.book.authors) == 1:
            default_author = author_id(self.book.authors[0].name)

        for src in posts:
            meta = resolve_meta(parse_post_header(src), src, default_author=default_author)
            if src.suffix == ".py":
                # Blog posts are never strict-fatal in v1 — warn only.
                def _on_post_cell_errors(cell_errors: list[CellError], *, _src: Path = src) -> None:
                    for e in cell_errors:
                        report.warnings.append(
                            f"{_src.name}: code cell {e.cell_index} raised "
                            f"{e.ename}: {e.evalue} (traceback published to post)"
                        )

                # Contain per-post render crashes (export timeout, marimo
                # failure) like TOC entries — one bad post must not abort
                # the whole build before mkdocs.yml is written.
                try:
                    body = self._render_notebook_body(src, on_cell_errors=_on_post_cell_errors)
                except Exception as exc:  # noqa: BLE001
                    report.errors.append(f"{src.name}: {exc.__class__.__name__}: {exc}")
                    continue
                if meta.title == src.stem:
                    h1 = _first_markdown_heading(body)
                    if h1:
                        meta.title = h1
            else:
                body = meta.body
            body = insert_teaser(body)
            staged = out_posts / (src.stem + ".md")
            staged.write_text(render_front_matter(meta) + "\n" + body, encoding="utf-8")
            report.pages += 1

        index = out_blog / "index.md"
        if not index.exists():
            index.write_text(f"# {self.book.blog.title}\n", encoding="utf-8")

        roster = build_author_roster(self.book.authors, read_authors_yml(self.book_dir))
        if roster:
            (out_blog / ".authors.yml").write_text(
                yaml.safe_dump({"authors": roster}, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )

    def _write_defaults(self, docs_dir: Path) -> None:
        """Copy the built-in default CSS / JS into the staging tree."""
        # Default CSS: use the theme palette from book.yml to override vars.
        assets_root = Path(__file__).parent / "assets"
        (docs_dir / "stylesheets").mkdir(parents=True, exist_ok=True)
        (docs_dir / "javascripts").mkdir(parents=True, exist_ok=True)

        extra_css = (assets_root / "extra.css").read_text(encoding="utf-8")
        if self.book.theme.palette.primary or self.book.theme.palette.accent:
            extra_css = _inject_palette(extra_css, self.book)
        (docs_dir / "stylesheets" / "extra.css").write_text(extra_css, encoding="utf-8")

        shutil.copy(assets_root / "mathjax.js", docs_dir / "javascripts" / "mathjax.js")
        shutil.copy(
            assets_root / "marimo_book.js",
            docs_dir / "javascripts" / "marimo_book.js",
        )

        # Optional: Jupyter-Book-style sidebar logo. Stage the stylesheet
        # only when opted in; shell.py picks it up via extra_css.
        if self.book.logo_placement == "sidebar":
            shutil.copy(
                assets_root / "logo_sidebar.css",
                docs_dir / "stylesheets" / "logo_sidebar.css",
            )

    def _stage_extra_css(self, docs_dir: Path, report: BuildReport) -> list[str]:
        """Copy author stylesheets into the staged tree.

        Returns the staged paths, which shell.py appends to mkdocs's
        ``extra_css`` after the built-in sheet so author rules win. A
        declared file that does not exist is a warning rather than an
        error: the site is still buildable, just unstyled.
        """
        staged: list[str] = []
        for relative in self.book.extra_css:
            source = self.book_dir / relative
            if not source.is_file():
                report.warnings.append(f"extra_css: {relative} not found under {self.book_dir}")
                continue
            destination = docs_dir / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)
            staged.append(relative.as_posix())
        return staged


# --- TOC traversal ----------------------------------------------------------


def _iter_file_entries(toc: list) -> list[FileEntry]:
    """Flatten the nested TOC into a list of FileEntries to render."""
    out: list[FileEntry] = []
    for entry in toc:
        if isinstance(entry, FileEntry):
            if not entry.hidden:
                out.append(entry)
        elif isinstance(entry, SectionEntry):
            out.extend(_iter_file_entries(entry.children))
        elif isinstance(entry, UrlEntry):
            continue
    return out


@cache
def _book_subpath_in_repo(book_dir: Path) -> str:
    """Return the book's path relative to its enclosing git repo, or "".

    Walks upward from ``book_dir`` looking for a ``.git`` directory or
    file (the latter for git worktrees). When found, returns the
    book's path relative to that repo root, posix-style. When not
    found (book.yml not inside a checked-out repo), returns an empty
    string and launch-button URLs fall back to assuming the book is
    at the repo root — the historical behavior.

    Used by ``stage_page`` to make the GitHub / molab / download
    launch buttons resolve correctly when ``book.yml`` lives in a
    subdirectory of its repo (e.g. ``docs/`` for marimo-book's own
    self-hosted documentation). Without this, a per-page GitHub
    button on ``content/index.md`` would link to
    ``https://github.com/<owner>/<repo>/blob/<branch>/content/index.md``,
    which 404s because the actual path is
    ``docs/content/index.md``.
    """
    book_dir = book_dir.resolve()
    for p in (book_dir, *book_dir.parents):
        if (p / ".git").exists():
            rel = book_dir.relative_to(p)
            return rel.as_posix() if rel != Path(".") else ""
    return ""


# --- Single-page staging ----------------------------------------------------


@dataclass
class StagedPage:
    """What :func:`stage_page` produced for one TOC entry.

    ``body`` is the pre-finalize content (no buttons, no link rewrites) —
    exactly what the transient cache stores so a later hit can re-finalize
    with fresh TOC/button context instead of re-executing the notebook.
    """

    path: Path
    body: str
    apply_rewrites: bool


def stage_page(
    book: Book,
    book_dir: Path,
    entry: FileEntry,
    docs_dir: Path,
    *,
    md_basenames: set[str] | None = None,
    sandbox: bool = False,
    index_source: Path | None = None,
    on_cell_errors: Callable[[list[CellError]], None] | None = None,
) -> StagedPage:
    """Render a single TOC entry into ``docs_dir``."""
    src_abs = (book_dir / entry.file).resolve()
    if not src_abs.exists():
        raise FileNotFoundError(f"TOC references missing file: {entry.file}")

    mode = entry.effective_mode(book.defaults.mode)
    if src_abs.suffix == ".py":
        # WASM pages always get the staging pipeline (PEP 723 block +
        # micropip bootstrap injected into the first cell, since the
        # islands runtime can't otherwise provision pure-Python PyPI
        # deps). Static / sandbox pages opt in via
        # ``dependencies.auto_pep723`` and only get the PEP 723 block;
        # the bootstrap is WASM-specific. The build never modifies the
        # source ``.py`` — it writes a sibling tempdir copy and feeds
        # marimo that copy. Sibling-tempdir location matches the
        # existing precompute pattern so cwd-based relative imports
        # inside the notebook still resolve.
        needs_pep723 = mode == "wasm" or book.dependencies.auto_pep723
        with _maybe_stage_with_pep723(
            src_abs,
            book.dependencies,
            enabled=needs_pep723,
            wasm_bootstrap=mode == "wasm",
        ) as staged:
            if mode == "wasm":
                # WASM-mode pages bypass our static cell rendering. Marimo's
                # islands runtime takes over in the browser; the body we
                # write here contains marimo's CDN-loaded scripts + the
                # ``<marimo-island>`` web components for each cell.
                body = render_wasm_page(
                    src_abs,
                    staged_source_path=staged,
                    timeout=book.defaults.execution_timeout,
                )
                apply_rewrites = False
            else:
                body = _render_marimo(
                    staged or src_abs, book, sandbox=sandbox, on_cell_errors=on_cell_errors
                )
                apply_rewrites = True
    elif src_abs.suffix == ".md":
        body = _render_markdown(src_abs)
        apply_rewrites = True
    else:
        raise ValueError(f"Unsupported file type for TOC entry: {entry.file}")

    dst = _finalize_page(
        book,
        book_dir,
        entry,
        docs_dir,
        body,
        apply_rewrites=apply_rewrites,
        md_basenames=md_basenames,
        index_source=index_source,
    )
    return StagedPage(dst, body, apply_rewrites)


def _finalize_page(
    book: Book,
    book_dir: Path,
    entry: FileEntry,
    docs_dir: Path,
    body: str,
    *,
    apply_rewrites: bool,
    md_basenames: set[str] | None = None,
    index_source: Path | None = None,
) -> Path:
    """Attach buttons + link-rewrites to a rendered ``body`` and write it.

    Split out of :func:`stage_page` so ``mode: cached`` pages run the exact
    same finishing pipeline on a body read from ``_rendered/`` as a freshly
    executed page does. Buttons and link-rewrites are applied here (not baked
    into the committed artifact) so config/TOC changes never invalidate it.

    Link-rewrites run for both static notebook prose and hand-authored
    Markdown; WASM bodies pass ``apply_rewrites=False`` because the body is
    marimo's own HTML, not our Markdown.
    """
    rel_under_docs = _doc_relpath_for(entry.file, index_source=index_source)
    dst = docs_dir / rel_under_docs
    dst.parent.mkdir(parents=True, exist_ok=True)
    buttons = render_button_row(
        book, Path(entry.file), repo_subpath=_book_subpath_in_repo(book_dir)
    )
    if apply_rewrites:
        body = apply_link_rewrites(body, md_basenames=md_basenames)
        if book.bibliography.files:
            # Finalize-time like the rewrites: cached bodies keep the raw
            # [@key] text, so .bib edits apply without invalidating renders.
            bib = load_bibliography(tuple(book_dir / f for f in book.bibliography.files))
            body = apply_citations(body, bib=bib, style=book.cite_style)
    dst.write_text(_compose_page(buttons, body), encoding="utf-8")
    return dst


def render_py_body(
    book: Book,
    book_dir: Path,
    entry: FileEntry,
    *,
    sandbox: bool = False,
    on_cell_errors: Callable[[list[CellError]], None] | None = None,
) -> str:
    """Execute a ``.py`` entry and return its rendered body (pre-finalize).

    This is the expensive, source-dependent output that ``mode: cached``
    commits to ``_rendered/``. It excludes buttons and link-rewrites so the
    committed artifact stays stable against config/TOC changes — those are
    re-applied cheaply at build time by :func:`_finalize_page`.
    """
    src_abs = (book_dir / entry.file).resolve()
    if not src_abs.exists():
        raise FileNotFoundError(f"TOC references missing file: {entry.file}")
    with _maybe_stage_with_pep723(
        src_abs,
        book.dependencies,
        enabled=book.dependencies.auto_pep723,
        wasm_bootstrap=False,
    ) as staged:
        return _render_marimo(
            staged or src_abs, book, sandbox=sandbox, on_cell_errors=on_cell_errors
        )


def _render_marimo(
    src: Path,
    book: Book,
    *,
    sandbox: bool = False,
    on_cell_errors: Callable[[list[CellError]], None] | None = None,
) -> str:
    exp = export_notebook(
        src,
        sandbox=sandbox,
        suppress_warnings=book.defaults.suppress_warnings,
        timeout=book.defaults.execution_timeout,
    )
    if on_cell_errors is not None:
        cell_errors = collect_cell_errors(exp)
        if cell_errors:
            on_cell_errors(cell_errors)
    return cells_to_markdown(
        exp,
        hide_first_code_cell=book.defaults.hide_first_code_cell,
        widget_defaults=book.widget_defaults or None,
    )


def _render_markdown(src: Path) -> str:
    return src.read_text(encoding="utf-8")


def _compose_page(buttons: str, body: str) -> str:
    if buttons:
        return f"{buttons}\n\n{body.lstrip()}"
    return body


def _doc_relpath_for(file_path: Path, *, index_source: Path | None = None) -> Path:
    """Map a TOC ``file:`` path to a path under ``docs/``.

    - Strip leading ``content/`` to keep URLs short (``/intro/`` not
      ``/content/intro/``).
    - Rewrite ``.py`` → ``.md`` so marimo notebooks land in docs_dir as the
      rendered markdown pages mkdocs expects.
    - If ``index_source`` matches ``file_path``, return ``index.md`` so the
      first TOC entry becomes the site's home page. mkdocs serves
      ``docs/index.md`` as ``/index.html``, which is what the header logo
      and bare-domain links resolve to.
    """
    if index_source is not None and Path(file_path) == Path(index_source):
        return Path("index.md")
    parts = file_path.parts
    if parts and parts[0] == _CONTENT_DIR:
        parts = parts[1:]
    p = Path(*parts) if parts else file_path
    if p.suffix == ".py":
        p = p.with_suffix(".md")
    return p


def _inject_palette(css: str, book: Book) -> str:
    """Prepend CSS variable overrides for the book's palette.

    Emits the same primary/accent values into both the light scheme
    (``:root``) and the dark scheme (``[data-md-color-scheme="slate"]``)
    using ``!important`` so the user's book.yml palette beats marimo-book's
    own dark-scheme indigo defaults declared further down in extra.css.
    """
    palette = book.theme.palette
    primary = palette.primary
    accent = palette.accent
    if not (primary or accent):
        return css

    def _block(selector: str) -> list[str]:
        out = [selector + " {"]
        if primary:
            out.append(f"  --md-primary-fg-color: {primary} !important;")
            out.append(f"  --md-typeset-a-color: {primary} !important;")
        if accent:
            out.append(f"  --md-accent-fg-color: {accent} !important;")
        out.append("}")
        return out

    lines = ["/* palette from book.yml */"]
    lines += _block(":root")
    lines += _block('[data-md-color-scheme="slate"]')
    lines.append("")
    return "\n".join(lines) + "\n" + css
