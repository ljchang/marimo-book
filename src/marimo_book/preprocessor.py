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

import hashlib
import json
import shutil
from dataclasses import dataclass, field
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from .config import Book, FileEntry, SectionEntry, UrlEntry
from .launch_buttons import render_button_row
from .shell import _nav_from_toc, emit_mkdocs_yml
from .transforms.link_rewrites import apply_link_rewrites
from .transforms.marimo_export import cells_to_markdown, export_notebook
from .transforms.precompute import (
    WidgetCandidate,
    estimate_renders_independent,
    page_excluded,
    precompute_page,
    scan_widgets,
)

# Directories and glob patterns of assets we copy verbatim when present.
_ASSET_DIRS: tuple[str, ...] = ("images", "Code", "data")

# Filename prefix stripped when computing the docs-relative path.
_CONTENT_DIR = "content"


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
_CACHE_SCHEMA_VERSION = 1
_CACHE_DIR_NAME = ".marimo_book_cache"
_CACHE_FILE_NAME = "manifest.json"


class BuildCache:
    """Per-file content cache for ``marimo export`` outputs.

    Each TOC entry resolves to a HIT (skip the expensive notebook export
    and reuse the staged ``.md``) or MISS (render fresh, record the new
    fingerprint). The cache is keyed by source content, the marimo-book
    version, and any ``book.yml`` field that affects rendering — so a
    schema change, tool upgrade, or relevant config change invalidates
    everything safely.

    Markdown TOC entries are NOT cached: their render is ~10 ms each and
    not worth the bookkeeping. Only ``.py`` notebook entries pass through
    the cache.
    """

    def __init__(self, book_dir: Path, book: Book, *, force_rebuild: bool = False) -> None:
        self.path = book_dir / _CACHE_DIR_NAME / _CACHE_FILE_NAME
        self.force_rebuild = force_rebuild
        self.tool_version = _resolve_tool_version()
        self.book_signature = _book_signature(book)
        self.entries: dict[str, dict] = {}
        self.dirty = False
        if not force_rebuild:
            self._load()

    def is_hit(self, src_rel: str, src_abs: Path, docs_dir: Path) -> bool:
        if self.force_rebuild:
            return False
        entry = self.entries.get(src_rel)
        if entry is None:
            return False
        out_abs = docs_dir / entry["out_path"]
        if not out_abs.exists():
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

    def record(self, src_rel: str, src_abs: Path, out_rel: str) -> None:
        try:
            mtime = src_abs.stat().st_mtime
            digest = _file_sha256(src_abs)
        except OSError:
            return
        self.entries[src_rel] = {
            "src_mtime": mtime,
            "src_hash": digest,
            "out_path": out_rel,
            "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
        }
        self.dirty = True

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
        self.dirty = False

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


def _resolve_tool_version() -> str:
    """Read the installed package version; fall back to a sentinel if missing."""
    try:
        return _pkg_version("marimo-book")
    except PackageNotFoundError:
        return "0.0.0+unknown"


def _book_signature(book: Book) -> str:
    """Hash ``book.yml`` fields whose changes invalidate rendered pages.

    Includes anything the preprocessor reads while rendering a notebook
    or applying link-rewrites: ``defaults`` (e.g. ``hide_first_code_cell``),
    ``dependencies`` (mode), ``widget_defaults`` (anywidget seed state),
    ``launch_buttons`` + ``repo`` + ``branch`` (button row), and the
    flattened TOC (link rewrites depend on which other pages exist).

    Excludes title / palette / fonts / analytics — those only affect
    ``mkdocs.yml`` emission, which is always re-run and cheap.
    """
    relevant: dict = {
        "widget_defaults": book.widget_defaults,
        "defaults": book.defaults.model_dump(mode="json"),
        "dependencies": book.dependencies.model_dump(mode="json"),
        "launch_buttons": book.launch_buttons.model_dump(mode="json"),
        "precompute": book.precompute.model_dump(mode="json"),
        "repo": book.repo,
        "branch": book.branch,
        "toc": [e.model_dump(mode="json") for e in book.toc],
    }
    payload = json.dumps(relevant, sort_keys=True, default=str)
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _splice_precomputed_body(original_page: str, result) -> str:
    """Replace the staged page's body with the precomputed version.

    The original page is ``<launch buttons block>\\n\\n<body>``. We
    preserve the launch-button row verbatim, inject the widget control
    after it, and replace the body with ``result.body`` (which already
    contains the cell wrappers + embedded lookup-table script blocks).

    If the page has no launch-button block (``repo`` not set in
    ``book.yml``), we just prepend the widget control to the body.
    """
    marker_open = '<div class="marimo-book-buttons">'
    marker_close = "</div>"
    if marker_open in original_page:
        head_end = original_page.index(marker_open)
        # Find the matching close — launch buttons render is one flat div.
        close_at = original_page.index(marker_close, head_end) + len(marker_close)
        head = original_page[:close_at]
        return head + "\n\n" + result.widget_html + "\n\n" + result.body
    return result.widget_html + "\n\n" + result.body


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
    ) -> None:
        self.book = book
        self.book_dir = Path(book_dir).resolve()
        # None = honour book.yml's dependencies.mode; True/False overrides.
        self.sandbox_override = sandbox_override
        # When True, every TOC entry is re-rendered regardless of cache state.
        # The cache is still updated so future builds without --rebuild benefit.
        self.rebuild = rebuild

    @property
    def sandbox(self) -> bool:
        """Effective sandbox setting for this build."""
        if self.sandbox_override is not None:
            return self.sandbox_override
        return self.book.dependencies.mode == "sandbox"

    # --- public API ----------------------------------------------------------

    def build(self, *, out_dir: Path, site_dir: Path | None = None) -> BuildReport:
        """Stage ``docs/`` and emit ``mkdocs.yml`` under ``out_dir``.

        ``site_dir`` is where ``mkdocs build`` will later emit the finished
        HTML. It defaults to a sibling of ``out_dir`` called ``_site``.
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

        file_entries = _iter_file_entries(self.book.toc)
        md_basenames = {_doc_relpath_for(e.file).with_suffix("").name for e in file_entries}

        cache = BuildCache(self.book_dir, self.book, force_rebuild=self.rebuild)

        for entry in file_entries:
            src_rel = str(entry.file)
            src_abs = (self.book_dir / entry.file).resolve()
            out_rel = _doc_relpath_for(entry.file).as_posix()
            try:
                # Notebook entries are the only ones worth caching: marimo
                # export takes seconds-to-minutes, vs ~10 ms for Markdown.
                if entry.file.suffix == ".py" and cache.is_hit(src_rel, src_abs, docs_dir):
                    report.pages_cached += 1
                else:
                    stage_page(
                        self.book,
                        self.book_dir,
                        entry,
                        docs_dir,
                        md_basenames=md_basenames,
                        sandbox=self.sandbox,
                    )
                    if entry.file.suffix == ".py":
                        cache.record(src_rel, src_abs, out_rel)
                    report.pages_rendered += 1
                report.pages += 1

                # Static-reactivity precompute: scan widgets, apply caps,
                # re-export per value, splice the lookup table into the
                # staged page so the JS shim can swap reactive cells.
                # TODO(v0.2): gate on `book.defaults.mode == "static"` once
                # WASM render mode lands — WASM pages don't need this.
                if entry.file.suffix == ".py" and self.book.precompute.enabled:
                    self._run_precompute(entry, src_abs, docs_dir, report)
            except Exception as exc:  # noqa: BLE001
                report.errors.append(f"{entry.file}: {exc.__class__.__name__}: {exc}")

        cache.save()

        nav = _nav_from_toc(self.book.toc)
        if self.book.include_changelog and self._stage_changelog(docs_dir):
            nav.append({"Changelog": "changelog.md"})
            report.pages += 1

        emit_mkdocs_yml(
            self.book,
            docs_dir=docs_dir.relative_to(out_dir),
            site_dir=site_dir,
            out_path=out_dir / "mkdocs.yml",
            nav=nav,
        )

        return report

    # --- internals -----------------------------------------------------------

    def _stage_assets(self, docs_dir: Path, report: BuildReport) -> None:
        for name in _ASSET_DIRS:
            src = self.book_dir / name
            if not src.exists():
                continue
            dst = docs_dir / name
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)

    def _run_precompute(
        self,
        entry: FileEntry,
        src_abs: Path,
        docs_dir: Path,
        report: BuildReport,
    ) -> None:
        """Detect widget candidates, apply caps, run the per-value re-export.

        Handles 1..N widgets per page. Each widget is precomputed
        independently; when widgets have disjoint downstream cells they
        coexist on one page. Joint widgets (sharing a downstream cell)
        still cause the page to render static — that's the next pass.
        """
        cfg = self.book.precompute
        if page_excluded(entry.file, cfg.exclude_pages):
            return

        try:
            source = src_abs.read_text(encoding="utf-8")
        except OSError:
            return
        candidates = scan_widgets(source)
        if not candidates:
            return

        # Per-widget count cap (cheap pre-check before any execution).
        kept: list[WidgetCandidate] = []
        for c in candidates:
            if len(c.values) > cfg.max_values_per_widget:
                report.warnings.append(
                    f"{entry.file}:{c.line} {c.var_name} "
                    f"({len(c.values)} values) exceeds "
                    f"max_values_per_widget ({cfg.max_values_per_widget}); "
                    f"rendered static."
                )
                report.widgets_skipped += 1
                continue
            kept.append(c)
        if not kept:
            return

        # Page-wide cap. For v1 (independent widgets), realistic cost
        # is ``1 + sum(values_i - 1)`` — sum, not cartesian product —
        # because each widget runs independently with others at default.
        # The legacy ``max_combinations_per_page`` name still fits the
        # joint-cross-product case (deferred), and we use it as the bound
        # on total renders here.
        renders = estimate_renders_independent(kept)
        if renders > cfg.max_combinations_per_page:
            report.warnings.append(
                f"{entry.file}: precompute would need {renders} re-exports across "
                f"{len(kept)} widgets, exceeding max_combinations_per_page "
                f"({cfg.max_combinations_per_page}); rendered static."
            )
            report.widgets_skipped += len(kept)
            return

        result = precompute_page(
            src_abs,
            kept,
            max_seconds=float(cfg.max_seconds_per_page),
            max_bytes=cfg.max_bytes_per_page,
            sandbox=self.sandbox,
        )
        if result.skipped:
            report.warnings.append(f"{entry.file}: {result.skip_reason}")
            report.widgets_skipped += len(kept)
            return
        if not result.reactive_cell_indices:
            return  # widgets exist but no downstream cells changed; static is fine

        out_rel = _doc_relpath_for(entry.file)
        staged_path = docs_dir / out_rel
        if not staged_path.exists():
            return
        original = staged_path.read_text(encoding="utf-8")
        staged_path.write_text(_splice_precomputed_body(original, result), encoding="utf-8")
        report.widgets_precomputed += len(kept)

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


# --- Single-page staging ----------------------------------------------------


def stage_page(
    book: Book,
    book_dir: Path,
    entry: FileEntry,
    docs_dir: Path,
    *,
    md_basenames: set[str] | None = None,
    sandbox: bool = False,
) -> Path:
    """Render a single TOC entry into ``docs_dir`` and return the output path."""
    src_abs = (book_dir / entry.file).resolve()
    if not src_abs.exists():
        raise FileNotFoundError(f"TOC references missing file: {entry.file}")

    rel_under_docs = _doc_relpath_for(entry.file)
    dst = docs_dir / rel_under_docs
    dst.parent.mkdir(parents=True, exist_ok=True)

    buttons = render_button_row(book, Path(entry.file))

    if src_abs.suffix == ".py":
        body = _render_marimo(src_abs, book, sandbox=sandbox)
    elif src_abs.suffix == ".md":
        body = _render_markdown(src_abs)
    else:
        raise ValueError(f"Unsupported file type for TOC entry: {entry.file}")

    # Link-rewrites run after both render paths so in-notebook prose and
    # hand-authored Markdown get the same treatment.
    body = apply_link_rewrites(body, md_basenames=md_basenames)

    full = _compose_page(buttons, body)
    dst.write_text(full, encoding="utf-8")
    return dst


def _render_marimo(src: Path, book: Book, *, sandbox: bool = False) -> str:
    exp = export_notebook(src, sandbox=sandbox)
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


def _doc_relpath_for(file_path: Path) -> Path:
    """Map a TOC ``file:`` path to a path under ``docs/``.

    - Strip leading ``content/`` to keep URLs short (``/intro/`` not
      ``/content/intro/``).
    - Rewrite ``.py`` → ``.md`` so marimo notebooks land in docs_dir as the
      rendered markdown pages mkdocs expects.
    """
    parts = file_path.parts
    if parts and parts[0] == _CONTENT_DIR:
        parts = parts[1:]
    p = Path(*parts) if parts else file_path
    if p.suffix == ".py":
        p = p.with_suffix(".md")
    return p


def _inject_palette(css: str, book: Book) -> str:
    """Prepend CSS variable overrides for the book's palette."""
    palette = book.theme.palette
    lines = ["/* palette from book.yml */", ":root {"]
    if palette.primary:
        lines.append(f"  --md-primary-fg-color: {palette.primary};")
    if palette.accent:
        lines.append(f"  --md-accent-fg-color: {palette.accent};")
    lines.append("}\n")
    return "\n".join(lines) + "\n" + css
