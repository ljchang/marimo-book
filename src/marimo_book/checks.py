"""Build-free validations behind ``marimo-book check``.

The point is speed and honesty: catch everything that would fail (or
silently do nothing) during a real build, in under a second, with no
notebook execution, no subprocesses, and no network. ``build --strict``
remains the authority on rendered output; this is the pre-flight.
"""

from __future__ import annotations

import importlib.util
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from .assignments import AssignmentError, AssignmentNotCachedError, resolve_assignment
from .config import Book, FileEntry, SectionEntry
from .preprocessor import _doc_relpath_for, _iter_file_entries, _render_body_signature
from .rendered_store import RenderedStore
from .transforms.citations import _CODE_FENCE_RE, _CODE_SPAN_RE

_SUPPORTED_SUFFIXES = {".md", ".py"}

# One row per feature needing an extra: (label for the message, probe
# module the extra installs — find_spec is cheap and import-free, the
# pip extra name, getter for whether the book enables it). Keeping the
# enabled-getter IN the row means adding a feature can't half-update two
# parallel structures and crash `check` with a KeyError.
_FEATURE_EXTRAS: tuple[tuple[str, str, str, Callable[[Book], bool]], ...] = (
    ("social_cards: true", "cairosvg", "social", lambda b: b.social_cards),
    ("pdf_export: true", "mkdocs_with_pdf", "pdf", lambda b: b.pdf_export),
    # NB: the dist is mkdocs-htmlproofer-plugin but the module it installs
    # is plain `htmlproofer`.
    ("check_external_links: true", "htmlproofer", "linkcheck", lambda b: b.check_external_links),
    ("api_docs: enabled", "mkdocstrings", "api", lambda b: b.api_docs.enabled),
    ("blog.rss", "mkdocs_rss_plugin", "blog", lambda b: b.blog.enabled and b.blog.rss),
    ("shell: zensical", "zensical", "zensical", lambda b: b.shell == "zensical"),
)

# Features whose mkdocs plugin zensical (0.0.x) silently ignores — the build
# prints "No issues found" and the feature just doesn't happen, even under
# --strict. Surfaced as errors so nobody ships a book missing its blog.
# Revisit against https://zensical.org/docs/compatibility/mkdocs/plugins/
# (tracked in ljchang/marimo-book#105).
_ZENSICAL_UNSUPPORTED: tuple[tuple[str, Callable[[Book], bool]], ...] = (
    ("social_cards", lambda b: b.social_cards),
    ("blog.enabled", lambda b: b.blog.enabled),
    ("check_external_links", lambda b: b.check_external_links),
    ("pdf_export", lambda b: b.pdf_export),
)

# Relative markdown link targets: `[text](target)` — captures the target up
# to the first `)`, `#` or whitespace so anchors/titles don't pollute it.
_MD_LINK_RE = re.compile(r"\[[^\]]*\]\(([^)#\s]+)[^)]*\)")


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
    _check_shell_support(book, report)
    _check_cached_freshness(book, book_dir, entries, report)
    _check_duplicate_outputs(entries, report)
    _check_inert_knobs(book, report)
    _check_workbench(book, book_dir, entries, report)
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
    for label, module, extra, is_enabled in _FEATURE_EXTRAS:
        if is_enabled(book) and not _module_available(module):
            report.errors.append(
                f"{label} needs the [{extra}] extra (pip install 'marimo-book[{extra}]')"
            )


def _check_shell_support(book: Book, report: CheckReport) -> None:
    if book.shell != "zensical":
        return
    for label, is_enabled in _ZENSICAL_UNSUPPORTED:
        if is_enabled(book):
            report.errors.append(
                f"{label}: not supported by shell: zensical — zensical ignores the "
                f"plugin without warning, so the feature would silently vanish "
                f"(use shell: mkdocs, or disable it)"
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
            # Warning, not error: plain `build` handles this by warning and
            # falling back to a live render (local authoring keeps working),
            # so a non-strict `check` must not be harsher than the build it
            # gates. `check --strict` promotes it — the CI posture, matching
            # `build --strict`'s hard-error on stale artifacts.
            reason = store.reason_stale(str(entry.file), src_abs, body_sig=body_sig)
            report.warnings.append(
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


# Packages that cannot load in Pyodide: native extensions with neither a
# bundled Pyodide build nor a wheel micropip can install. A notebook that
# imports one can't boot in the browser, so a run/edit view on it would only
# ever show an install error. Warned, not errored: the list is a heuristic.
#
# Checked in a browser (2026-09-15) by asking micropip to install each — do not
# add a package here without doing the same, because "has native code" is not
# the test: polars is Rust to the core and installs fine, and pyarrow (22.0.0)
# ships in the Pyodide release marimo pins. Pure-Python packages never belong
# here whatever they wrap (nibabel, nilearn), and neither do the ones Pyodide
# bundles (lxml, opencv-python, scikit-learn). `jax` stays because jaxlib,
# which it is useless without, has no wheel Pyodide can load.
_NO_PYODIDE_WHEEL = frozenset(
    {
        "torch",
        "torchvision",
        "torchaudio",
        "tensorflow",
        "jax",
        "jaxlib",
        "numba",
        "cupy",
        "psutil",
    }
)


#: Specifier kinds whose loss can select a *different* release: an exact pin, a
#: compatible release, an upper bound, or an exclusion. ``!=`` belongs here for
#: the opposite reason to a lower bound — ``numpy!=2.0.0`` says the author knows
#: 2.0.0 is broken, and dropping it installs precisely 2.0.0 if that is the
#: newest stable.
_RISKY_OPERATORS = ("==", "===", "~=", "<", "!=")


def _staged_requirements(path: Path, book: Book, deps: list[str] | None = None) -> list[str] | None:
    """The PEP 723 dependencies the build stages for ``path``, as the browser
    would see them — or ``None`` if they cannot be determined.

    Reproduces ``stage_workbench_notebook``: the same ``derive_dependencies``
    arguments, then ``write_pep723_block``, whose ``preserve_existing`` merge
    lets the notebook's own block win by canonical name. A requirement the
    block overrides never reaches the reader, so flagging the union would warn
    about something nobody installs.

    The result is then filtered the way marimo filters it before installing, so
    an entry excluded from emscripten by an environment marker is not reported.
    """
    from .transforms.pep723 import (
        derive_dependencies,
        read_existing_dependencies,
        write_pep723_block,
    )

    try:
        source = path.read_text(encoding="utf-8")
        if deps is None:
            deps = derive_dependencies(
                source,
                extras=book.dependencies.extras,
                overrides=book.dependencies.overrides,
                pin=book.dependencies.pin,
            )
        staged = read_existing_dependencies(write_pep723_block(source, deps)) or []
        return _installed_in_browser(staged)
    except Exception:  # noqa: BLE001 - a malformed block is reported at build time
        return None


def _installed_in_browser(requirements: list[str]) -> list[str]:
    """The subset marimo would actually install in Pyodide.

    Mirrors ``filter_requirements_for_emscripten``, which marimo runs before it
    installs, so an entry like ``pywin32; sys_platform == "win32"`` is dropped
    rather than reported. Falls back to the unfiltered list when marimo is not
    importable, since a missing filter should not fail the check.
    """
    try:
        from marimo._runtime.packages.utils import filter_requirements_for_emscripten
    except ImportError:  # pragma: no cover - marimo is a build dependency
        # Drop anything carrying a marker rather than keeping it. If marimo
        # moves this helper, an unfiltered list would start flagging
        # marker-guarded entries and turn `check --strict` red with no hint
        # that the filter had vanished; under-reporting is the safe direction
        # for a warning.
        return [r for r in requirements if ";" not in r]
    return list(filter_requirements_for_emscripten(requirements))


def _is_pinned(requirement: str) -> bool:
    """Whether dropping this requirement's specifier could change the version.

    A plain lower bound (``>=2``) is usually satisfied by whatever the bare name
    resolves to, so flagging it would turn ``check --strict`` red for books that
    are fine. With one exception, which is the case this check exists for: a
    lower bound naming a *pre-release*. Installers skip pre-releases unless a
    specifier asks for one, so ``nltools>=0.6.0.dev2`` resolves to the newest
    stable — 0.5.1, which cannot run in Pyodide — exactly as an exact pin does.

    A URL requirement (``name @ https://…``) is not "pinned" for this purpose:
    marimo's strip leaves those intact, so they do reach the browser as written.
    """
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.version import InvalidVersion, Version

    try:
        parsed = Requirement(requirement)
    except InvalidRequirement:
        return False
    if parsed.url is not None:
        return False

    for spec in parsed.specifier:
        if spec.operator.startswith(_RISKY_OPERATORS):
            return True
        if spec.operator in (">=", ">"):
            try:
                if Version(spec.version).is_prerelease:
                    return True
            except InvalidVersion:
                continue
    return False


def _requirement_name(requirement: str) -> str:
    """Canonical project name of a PEP 508 requirement string (``torch!=1.9`` → ``torch``)."""
    from packaging.requirements import InvalidRequirement, Requirement
    from packaging.utils import canonicalize_name

    try:
        return canonicalize_name(Requirement(requirement).name)
    except InvalidRequirement:
        return requirement.split("[")[0].split(";")[0].strip().lower()


def _check_workbench(
    book: Book, book_dir: Path, entries: list[FileEntry], report: CheckReport
) -> None:
    """``views`` / ``open_in`` must be consistent, and only make sense on notebooks."""
    from .transforms.pep723 import derive_dependencies

    # Collected across pages: `extras` are book-wide, so the same requirement
    # would otherwise be reported once per run/edit page.
    pinned: dict[str, list[str]] = {}

    for entry in entries:
        views = entry.effective_views(book.defaults)
        # Same precedence as FileEntry.effective_open_in: an entry's own
        # open_in must be one of its views; the book-wide open_in is only a
        # preference (validated against defaults.views by the model) and a
        # page that narrows its views simply falls back to its first view.
        if entry.open_in is not None and entry.open_in not in views:
            report.errors.append(
                f"{entry.file}: open_in: {entry.open_in!r} is not one of this page's views {views}"
            )
        if entry.file.suffix != ".py" and (entry.views is not None and views != ["read"]):
            report.errors.append(
                f"{entry.file}: views other than [read] only apply to marimo notebooks"
            )
        asg_src: Path | None = None
        if entry.assignment is not None:
            try:
                # No network in check: a slug the build has not fetched yet is
                # the build's job, not an error; a slug with no grader: is.
                resolved = resolve_assignment(entry, book, book_dir, fetch=False)
            except AssignmentNotCachedError:
                pass
            except AssignmentError as e:
                report.errors.append(f"{entry.file}: {e}")
            else:
                asg_src = resolved.src
                report.warnings.extend(f"{entry.file}: {note}" for note in resolved.notes)
                if asg_src.suffix != ".py":
                    report.errors.append(
                        f"{entry.file}: assignment must be a marimo notebook ({entry.assignment})"
                    )
                    asg_src = None
                elif "# /// script" not in asg_src.read_text(encoding="utf-8"):
                    report.warnings.append(
                        f"{entry.file}: assignment {entry.assignment} has no PEP 723 block — "
                        "a grader-published student notebook carries its identity there"
                    )
        # An assignment boots in the drawer through the same
        # `stage_workbench_notebook` call with the same `book.dependencies`, so
        # its block reaches the browser exactly as a chapter's does — and a
        # chapter with `views: [read]` can still carry one.
        if asg_src is not None:
            for requirement in _staged_requirements(asg_src, book) or []:
                if _is_pinned(requirement):
                    pinned.setdefault(requirement, []).append(str(entry.assignment))

        if not entry.uses_workbench(book.defaults):
            continue
        src = book_dir / entry.file
        if not src.exists():
            continue  # reported by _check_toc_files
        try:
            source = src.read_text(encoding="utf-8")
            # The same arguments `stage_workbench_notebook` uses, or this
            # checks something the build never stages.
            deps = derive_dependencies(
                source,
                extras=book.dependencies.extras,
                overrides=book.dependencies.overrides,
                pin=book.dependencies.pin,
            )
        except Exception:  # noqa: BLE001 - a syntax error is reported at build time
            continue

        # Deliberately its own try, and after `deps`: a malformed block or an
        # unparseable marker raises here, and folding that into the block above
        # would swallow the no-wheel warning too — a page importing torch would
        # go unreported because of an unrelated fault.
        staged = _staged_requirements(src, book, deps=deps)

        # `staged` when it could be computed: a notebook that hand-lists a
        # package in its own block without importing it is staged with it, and
        # `deps` (imports + extras) would never see it.
        names = {_requirement_name(d) for d in (staged if staged is not None else deps)}
        bad = sorted(names & _NO_PYODIDE_WHEEL)
        if bad:
            report.warnings.append(
                f"{entry.file}: views include run/edit but the notebook imports "
                f"{', '.join(bad)}, which cannot run in the browser (no Pyodide wheel)"
            )

        # marimo installs script-metadata dependencies by *name*: its
        # `strip_requirement_name` drops version specifiers before handing them
        # to micropip (marimo/_pyodide/pyodide_session.py::find_packages). So a
        # pin in the block is advisory in the browser — the reader gets
        # whatever the bare name resolves to, which is the newest *stable*
        # release. dartbrains pinned `nltools==0.6.0.dev2`; readers got 0.5.1,
        # which needs numpy<1.24 and has no Pyodide wheel, and the boot failed.
        for requirement in staged or ():
            if _is_pinned(requirement):
                pinned.setdefault(requirement, []).append(str(entry.file))

    if pinned:
        why = (
            "marimo drops version specifiers when installing in the browser, so "
            "the reader gets whatever the bare name resolves to — the newest "
            "*stable* release (marimo-team/marimo#10870)."
        )
        if book.dependencies.pin == "env":
            # `pin: env` stamps `==<installed>` onto every derived requirement,
            # so listing them would inline the book's whole dependency set and
            # the per-package advice would be unactionable.
            report.warnings.append(
                f"dependencies.pin: env has no effect on run/edit pages — {why} "
                f"The staged pins are advisory in the browser; readers install "
                f"whatever is newest. Use pin: none for a book with run/edit "
                f"views, or keep those pages read-only."
            )
        else:
            # Attributed per requirement: a book-wide `extras` pin lands on
            # every page while a notebook's own block lands on one, and a single
            # page count would claim the wrong thing about both.
            listed = "; ".join(
                f"{req} ({', '.join(sorted(set(pages)))})" for req, pages in sorted(pinned.items())
            )
            report.warnings.append(
                f"pinned dependencies on run/edit pages: {listed}. {why} Offer "
                f"run/edit there only if the unpinned version works in Pyodide."
            )


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
    from pybtex.database import parse_file

    from .transforms.citations import _CITE_RE, load_bibliography

    for f in book.bibliography.files:
        bib_abs = book_dir / f
        if not bib_abs.exists():
            report.errors.append(f"bibliography: file not found: {f}")
            continue
        # The build skips unparsable files silently (it must not crash over
        # a bibliography typo); this is the loud pre-flight for those too —
        # otherwise a syntax error surfaces only as a confusing cascade of
        # unknown-key warnings.
        try:
            parse_file(str(bib_abs), bib_format="bibtex")
        except Exception as exc:  # noqa: BLE001
            report.errors.append(f"bibliography: {f} failed to parse: {exc}")
    bib = load_bibliography(tuple(book_dir / f for f in book.bibliography.files))
    seen: set[tuple[str, str]] = set()
    for entry in entries:
        src = book_dir / entry.file
        if src.suffix != ".md" or not src.exists():
            continue
        text = _CODE_SPAN_RE.sub("", _CODE_FENCE_RE.sub("", src.read_text(encoding="utf-8")))
        for match in _CITE_RE.finditer(text):
            for raw in match.group(1).split(";"):
                key = raw.strip().lstrip("@")
                if key not in bib and (str(entry.file), key) not in seen:
                    seen.add((str(entry.file), key))
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
    # Validate against STAGED names, exactly as the build's link rewriter
    # does — the first TOC entry stages as index.md, so a link to its source
    # name would not resolve on the built site.
    index_source = Path(entries[0].file) if entries else None
    md_basenames = {
        _doc_relpath_for(entry.file, index_source=index_source).with_suffix("").name
        for entry in entries
    }
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
