"""Build-free validations behind ``marimo-book check``.

The point is speed and honesty: catch everything that would fail (or
silently do nothing) during a real build, in under a second, with no
notebook execution, no subprocesses, and no network. ``build --strict``
remains the authority on rendered output; this is the pre-flight.
"""

from __future__ import annotations

import importlib.util
import re
from dataclasses import dataclass, field
from pathlib import Path

from .config import Book, FileEntry, SectionEntry
from .preprocessor import _doc_relpath_for, _iter_file_entries, _render_body_signature
from .rendered_store import RenderedStore

_SUPPORTED_SUFFIXES = {".md", ".py"}

# Enabled-feature → (probe module, extra name). The probe is a module the
# extra installs; find_spec is cheap and import-free.
_FEATURE_EXTRAS: tuple[tuple[str, str, str], ...] = (
    ("social_cards", "cairosvg", "social"),
    ("pdf_export", "mkdocs_with_pdf", "pdf"),
    ("check_external_links", "mkdocs_htmlproofer_plugin", "linkcheck"),
    ("api_docs", "mkdocstrings", "api"),
    ("blog_rss", "mkdocs_rss_plugin", "blog"),
)

# Relative markdown link targets: `[text](target)` — captures the target up
# to the first `)`, `#` or whitespace so anchors/titles don't pollute it.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)[^)]*\)")

# Regions whose "links" are examples, not links: fenced blocks and inline
# code spans. Stripped before the link scan.
_CODE_FENCE_RE = re.compile(r"^(```|~~~).*?^\1\s*$", re.MULTILINE | re.DOTALL)
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")


@dataclass
class CheckReport:
    """Outcome of ``run_checks`` — printable, exit-code-ready."""

    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return not self.errors


def _module_available(name: str) -> bool:
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        return False


def run_checks(book: Book, book_dir: Path) -> CheckReport:
    """Validate a loaded book against its directory. Never executes code."""
    book_dir = Path(book_dir).resolve()
    report = CheckReport()
    entries = _iter_file_entries(book.toc)

    _check_toc_files(book, book_dir, entries, report)
    _check_asset_paths(book, book_dir, report)
    _check_extras(book, report)
    _check_cached_freshness(book, book_dir, entries, report)
    _check_duplicate_outputs(entries, report)
    _check_inert_knobs(book, report)
    _check_empty_sections(book.toc, report)
    _check_internal_links(book, book_dir, entries, report)
    _check_bibliography(book, book_dir, entries, report)
    return report


# --- errors -------------------------------------------------------------------


def _check_toc_files(
    book: Book, book_dir: Path, entries: list[FileEntry], report: CheckReport
) -> None:
    for entry in entries:
        src = book_dir / entry.file
        if not src.exists():
            report.errors.append(f"{entry.file}: TOC references a missing file")
        elif src.suffix not in _SUPPORTED_SUFFIXES:
            report.errors.append(
                f"{entry.file}: unsupported file type (TOC entries must be .md or .py)"
            )


def _check_asset_paths(book: Book, book_dir: Path, report: CheckReport) -> None:
    for label, value in (("logo", book.logo), ("favicon", book.favicon)):
        if value is not None and not (book_dir / value).exists():
            report.errors.append(f"{label}: file not found: {value}")
    if book.api_docs.enabled:
        for p in book.api_docs.paths:
            if not (book_dir / p).resolve().exists():
                report.errors.append(f"api_docs.paths: directory not found: {p}")
    if book.blog.enabled and not (book_dir / book.blog.dir).exists():
        report.errors.append(f"blog: source directory not found: {book.blog.dir}/")


def _check_extras(book: Book, report: CheckReport) -> None:
    enabled = {
        "social_cards": book.social_cards,
        "pdf_export": book.pdf_export,
        "check_external_links": book.check_external_links,
        "api_docs": book.api_docs.enabled,
        "blog_rss": book.blog.enabled and book.blog.rss,
    }
    labels = {"blog_rss": "blog.rss"}
    for feature, module, extra in _FEATURE_EXTRAS:
        if enabled[feature] and not _module_available(module):
            label = labels.get(feature, f"{feature}: true")
            report.errors.append(
                f"{label} needs the [{extra}] extra (pip install 'marimo-book[{extra}]')"
            )


def _check_cached_freshness(
    book: Book, book_dir: Path, entries: list[FileEntry], report: CheckReport
) -> None:
    cached = [
        e
        for e in entries
        if e.file.suffix == ".py" and e.effective_mode(book.defaults.mode) == "cached"
    ]
    if not cached:
        return
    store = RenderedStore(book_dir)
    body_sig = _render_body_signature(book)
    for entry in cached:
        src_abs = (book_dir / entry.file).resolve()
        if not src_abs.exists():
            continue  # already an error from _check_toc_files
        if not store.is_fresh(str(entry.file), src_abs, body_sig=body_sig):
            reason = store.reason_stale(str(entry.file), src_abs, body_sig=body_sig)
            report.errors.append(
                f"{entry.file}: mode=cached but {reason}; "
                f"run `marimo-book render` and commit _rendered/"
            )


def _check_duplicate_outputs(entries: list[FileEntry], report: CheckReport) -> None:
    # Mirrors the build's staging rule: the first entry becomes index.md.
    index_source = Path(entries[0].file) if entries else None
    seen: dict[str, Path] = {}
    for entry in entries:
        out = _doc_relpath_for(entry.file, index_source=index_source).as_posix()
        if out in seen:
            report.errors.append(
                f"{entry.file}: stages to '{out}', which {seen[out]} also stages to — "
                f"one page would silently overwrite the other"
            )
        else:
            seen[out] = entry.file


# --- warnings -------------------------------------------------------------------


def _check_inert_knobs(book: Book, report: CheckReport) -> None:
    for name in ("binder", "colab", "wasm"):
        if getattr(book.launch_buttons, name, False):
            report.warnings.append(
                f"launch_buttons.{name}: true is reserved but not implemented — "
                f"no button will render"
            )
    any_button = book.launch_buttons.molab or book.launch_buttons.github
    if any_button and not book.repo:
        report.warnings.append(
            "launch_buttons are enabled but repo: is unset — the button row renders empty"
        )


def _check_empty_sections(toc: list, report: CheckReport) -> None:
    for entry in toc:
        if isinstance(entry, SectionEntry):
            if not entry.children:
                report.warnings.append(
                    f"section '{entry.section}' has no children and will not render"
                )
            else:
                _check_empty_sections(entry.children, report)


def _check_bibliography(
    book: Book, book_dir: Path, entries: list[FileEntry], report: CheckReport
) -> None:
    """Missing .bib files are errors; unknown [@key]s in .md prose warn.

    The build itself stays quiet on unknown keys (they render verbatim,
    which is self-evident on the page) — this is the loud pre-flight.
    """
    if not book.bibliography.files:
        return
    from .transforms.citations import _CITE_RE, load_bibliography

    missing = [f for f in book.bibliography.files if not (book_dir / f).exists()]
    for f in missing:
        report.errors.append(f"bibliography: file not found: {f}")
    bib = load_bibliography(tuple(book_dir / f for f in book.bibliography.files))
    for entry in entries:
        src = book_dir / entry.file
        if src.suffix != ".md" or not src.exists():
            continue
        text = _CODE_SPAN_RE.sub("", _CODE_FENCE_RE.sub("", src.read_text(encoding="utf-8")))
        for match in _CITE_RE.finditer(text):
            for raw in match.group(1).split(";"):
                key = raw.strip().lstrip("@")
                if key not in bib:
                    report.warnings.append(
                        f"{entry.file}: citation key [@{key}] not found in bibliography"
                    )


def _check_internal_links(
    book: Book, book_dir: Path, entries: list[FileEntry], report: CheckReport
) -> None:
    """Static pass over .md sources for broken relative links.

    A relative target is fine if it exists on disk next to the source, or if
    its basename matches another TOC page (the link-rewrite convention maps
    ``page.md`` links to whichever entry stages under that name). Notebook
    prose is skipped — it needs a render, which ``build --strict`` covers.
    Links inside fenced blocks / inline code are examples, not links.
    """
    md_basenames = {entry.file.with_suffix("").name for entry in entries}
    if book.include_changelog:
        # Generated page: staged from CHANGELOG.md at build time.
        md_basenames.add("changelog")
    for entry in entries:
        src = book_dir / entry.file
        if src.suffix != ".md" or not src.exists():
            continue
        text = src.read_text(encoding="utf-8")
        text = _CODE_FENCE_RE.sub("", text)
        text = _CODE_SPAN_RE.sub("", text)
        for match in _MD_LINK_RE.finditer(text):
            target = match.group(1)
            if "://" in target or target.startswith(("mailto:", "/", "data:")):
                continue
            if (src.parent / target).exists():
                continue
            if Path(target).suffix in {".md", ".py", ".ipynb", ""}:
                stem = Path(target).with_suffix("").name
                if stem in md_basenames:
                    continue
            report.warnings.append(f"{entry.file}: broken relative link '{target}'")
