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

import shutil
from dataclasses import dataclass, field
from pathlib import Path

from .config import Book, FileEntry, SectionEntry, UrlEntry
from .launch_buttons import render_button_row
from .shell import emit_mkdocs_yml
from .transforms.marimo_export import cells_to_markdown, export_notebook
from .transforms.md_roles import apply_md_transforms

# Directories and glob patterns of assets we copy verbatim when present.
_ASSET_DIRS: tuple[str, ...] = ("images", "Code", "data")

# Filename prefix stripped when computing the docs-relative path.
_CONTENT_DIR = "content"


@dataclass
class BuildReport:
    """Summary of what the preprocessor produced."""

    pages: int = 0
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


class Preprocessor:
    """Stateful driver for a single build.

    Constructing the preprocessor does not touch the filesystem; work
    happens in :meth:`build`.
    """

    def __init__(self, book: Book, *, book_dir: Path) -> None:
        self.book = book
        self.book_dir = Path(book_dir).resolve()

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

        # Clean staging tree — always rebuild in v0.1.
        if docs_dir.exists():
            shutil.rmtree(docs_dir)
        docs_dir.mkdir(parents=True, exist_ok=True)

        report = BuildReport()

        self._stage_assets(docs_dir, report)
        self._write_defaults(docs_dir)

        for entry in _iter_file_entries(self.book.toc):
            try:
                stage_page(self.book, self.book_dir, entry, docs_dir)
                report.pages += 1
            except Exception as exc:  # noqa: BLE001
                report.errors.append(
                    f"{entry.file}: {exc.__class__.__name__}: {exc}"
                )

        emit_mkdocs_yml(
            self.book,
            docs_dir=docs_dir.relative_to(out_dir),
            site_dir=site_dir,
            out_path=out_dir / "mkdocs.yml",
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

    def _write_defaults(self, docs_dir: Path) -> None:
        """Copy the built-in default CSS / JS into the staging tree."""
        # Default CSS: use the theme palette from book.yml to override vars.
        assets_root = Path(__file__).parent / "assets"
        (docs_dir / "stylesheets").mkdir(parents=True, exist_ok=True)
        (docs_dir / "javascripts").mkdir(parents=True, exist_ok=True)

        extra_css = (assets_root / "extra.css").read_text(encoding="utf-8")
        if self.book.theme.palette.primary or self.book.theme.palette.accent:
            extra_css = _inject_palette(extra_css, self.book)
        (docs_dir / "stylesheets" / "extra.css").write_text(
            extra_css, encoding="utf-8"
        )

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


def stage_page(book: Book, book_dir: Path, entry: FileEntry, docs_dir: Path) -> Path:
    """Render a single TOC entry into ``docs_dir`` and return the output path."""
    src_abs = (book_dir / entry.file).resolve()
    if not src_abs.exists():
        raise FileNotFoundError(f"TOC references missing file: {entry.file}")

    rel_under_docs = _doc_relpath_for(entry.file)
    dst = docs_dir / rel_under_docs
    dst.parent.mkdir(parents=True, exist_ok=True)

    buttons = render_button_row(book, Path(entry.file))

    if src_abs.suffix == ".py":
        body = _render_marimo(src_abs, book)
    elif src_abs.suffix == ".md":
        body = _render_markdown(src_abs)
    else:
        raise ValueError(f"Unsupported file type for TOC entry: {entry.file}")

    full = _compose_page(buttons, body)
    dst.write_text(full, encoding="utf-8")
    return dst


def _render_marimo(src: Path, book: Book) -> str:
    exp = export_notebook(src)
    return cells_to_markdown(
        exp,
        hide_first_code_cell=book.defaults.hide_first_code_cell,
        widget_defaults=book.widget_defaults or None,
    )


def _render_markdown(src: Path) -> str:
    raw = src.read_text(encoding="utf-8")
    return apply_md_transforms(raw)


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
