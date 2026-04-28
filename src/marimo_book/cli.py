"""``marimo-book`` command-line interface.

All commands are dispatched through the Typer ``app`` object. Commands are
stubs in v0.1.0.dev0 and will be fleshed out as the preprocessor and shell
generator land.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import typer
from pydantic import ValidationError

from marimo_book import __version__
from marimo_book.config import load_book
from marimo_book.preprocessor import Preprocessor
from marimo_book.transforms.pep723 import derive_dependencies, write_pep723_block

app = typer.Typer(
    name="marimo-book",
    help="Build clean, searchable static books from marimo notebooks and Markdown.",
    no_args_is_help=True,
    add_completion=False,
)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"marimo-book {__version__}")
        raise typer.Exit()


@app.callback()
def _main(
    version: bool = typer.Option(
        False,
        "--version",
        callback=_version_callback,
        is_eager=True,
        help="Show the installed version and exit.",
    ),
) -> None:
    pass


# --- commands ----------------------------------------------------------------


@app.command("new")
def new_book(
    directory: Path = typer.Argument(..., help="Target directory for the new book."),
    force: bool = typer.Option(
        False,
        "--force",
        help="Write into an existing non-empty directory (may overwrite files).",
    ),
) -> None:
    """Scaffold a new book in ``DIRECTORY``.

    Copies a minimal starter layout (book.yml, content/intro.md,
    content/example.py, .gitignore, README.md, GitHub Pages workflow) into
    the target directory. After it finishes, ``cd`` into the directory and
    run ``marimo-book serve``.
    """
    target = directory.resolve()
    if target.exists() and any(target.iterdir()) and not force:
        typer.echo(
            f"error: {target} already exists and is not empty. "
            f"Pass --force to scaffold into it anyway.",
            err=True,
        )
        raise typer.Exit(code=2)

    scaffold_src = Path(__file__).parent / "assets" / "scaffold"
    if not scaffold_src.is_dir():
        typer.echo(
            f"error: scaffold assets missing at {scaffold_src}. This is a packaging bug.",
            err=True,
        )
        raise typer.Exit(code=1)

    target.mkdir(parents=True, exist_ok=True)
    _copy_scaffold(scaffold_src, target)

    typer.echo(f"Created new marimo-book at {target}")
    typer.echo("")
    typer.echo("Next steps:")
    typer.echo(f"  cd {target}")
    typer.echo("  marimo-book serve")
    typer.echo("")
    typer.echo("Edit book.yml to set your title, repo URL, and launch-button targets.")


def _copy_scaffold(src: Path, dst: Path) -> None:
    """Recursively copy the scaffold tree, preserving hidden files and dirs."""
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        out = dst / rel
        if item.is_dir():
            out.mkdir(parents=True, exist_ok=True)
        else:
            out.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(item, out)


@app.command("build")
def build(
    book_file: Path = typer.Option(
        Path("book.yml"),
        "--book",
        "-b",
        help="Path to the book.yml config.",
        exists=True,
        dir_okay=False,
    ),
    output: Path = typer.Option(
        Path("_site"),
        "--output",
        "-o",
        help="Output directory for the built site.",
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail on warnings (unresolved refs, missing files, etc.).",
    ),
    clean: bool = typer.Option(
        False,
        "--clean",
        help="Remove _site_src/ and build cache before building.",
    ),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help=(
            "Re-render every notebook regardless of cache state. Use when you "
            "changed something the cache can't detect (a data file the notebook "
            "reads, an env-mode dep upgrade, etc.). --clean implies --rebuild."
        ),
    ),
    sandbox: bool | None = typer.Option(
        None,
        "--sandbox/--no-sandbox",
        help=(
            "Force per-notebook PEP 723 sandbox mode (uv) on or off, "
            "ignoring book.yml's dependencies.mode. Default: follow book.yml."
        ),
    ),
) -> None:
    """Build the static site from ``book.yml``."""
    book = _load_or_exit(book_file)
    book_dir = book_file.resolve().parent
    site_src = book_dir / "_site_src"
    site_dir = Path(output).resolve() if output.is_absolute() else (book_dir / output).resolve()

    if clean:
        for target in (site_src, site_dir, book_dir / ".marimo_book_cache"):
            if target.exists():
                shutil.rmtree(target)

    # --clean removes the cache directory above, so the next build is
    # cold either way; setting rebuild=True is just for clarity.
    pre = Preprocessor(
        book,
        book_dir=book_dir,
        sandbox_override=sandbox,
        rebuild=rebuild or clean,
    )
    typer.echo(
        f"Preprocessing '{book.title}' ({_count_toc(book.toc)} pages, "
        f"deps={'sandbox' if pre.sandbox else 'env'})..."
    )
    report = pre.build(out_dir=site_src, site_dir=site_dir)

    for warn in report.warnings:
        typer.echo(f"  warning: {warn}", err=True)
    for err in report.errors:
        typer.echo(f"  error: {err}", err=True)
    if not report.ok:
        typer.echo(f"Preprocessing failed ({len(report.errors)} errors).", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Preprocessing OK ({_summarise_report(report)} at {site_src}).")

    typer.echo(f"Running mkdocs build → {site_dir}")
    build_cmd = [sys.executable, "-m", "mkdocs", "build"]
    if strict:
        build_cmd.append("--strict")
    build_cmd.extend(["--config-file", str(site_src / "mkdocs.yml")])
    result = subprocess.run(build_cmd, cwd=site_src)
    if result.returncode != 0:
        typer.echo("mkdocs build failed.", err=True)
        raise typer.Exit(code=result.returncode)
    typer.echo(f"Done. Site at {site_dir}")


@app.command("serve")
def serve(
    book_file: Path = typer.Option(
        Path("book.yml"),
        "--book",
        "-b",
        help="Path to the book.yml config.",
        exists=True,
        dir_okay=False,
    ),
    host: str = typer.Option("127.0.0.1", "--host", help="Dev server host."),
    port: int = typer.Option(8000, "--port", help="Dev server port."),
    no_watch: bool = typer.Option(
        False,
        "--no-watch",
        help="Serve without a source watcher (useful for debugging).",
    ),
    rebuild: bool = typer.Option(
        False,
        "--rebuild",
        help=(
            "Re-render every notebook on the initial build (ignores cache). "
            "Watcher rebuilds always honour the cache; use this only when the "
            "first build needs to be cold."
        ),
    ),
    sandbox: bool | None = typer.Option(
        None,
        "--sandbox/--no-sandbox",
        help=(
            "Force per-notebook PEP 723 sandbox mode on or off for this "
            "serve session, ignoring book.yml. Note: sandbox mode adds "
            "~5-10s to every rebuild; leave off for fast iteration."
        ),
    ),
) -> None:
    """Serve the book locally with live reload.

    Runs an initial build, then starts mkdocs's dev server with livereload.
    A watchdog observer re-runs the preprocessor on changes to book.yml or
    content/*, and mkdocs picks up the resulting _site_src/docs/ updates to
    refresh the browser. Ctrl-C stops both the observer and mkdocs cleanly.
    """
    from .watcher import start_watcher

    book = _load_or_exit(book_file)
    book_dir = book_file.resolve().parent
    site_src = book_dir / "_site_src"

    pre = Preprocessor(book, book_dir=book_dir, sandbox_override=sandbox, rebuild=rebuild)
    typer.echo(
        f"Preprocessing '{book.title}' ({_count_toc(book.toc)} pages, "
        f"deps={'sandbox' if pre.sandbox else 'env'})..."
    )
    report = pre.build(out_dir=site_src)
    _report_build(report)
    if not report.ok:
        raise typer.Exit(code=1)
    typer.echo(f"Preprocessing OK ({_summarise_report(report)} at {site_src}).")

    typer.echo(f"Starting mkdocs serve on http://{host}:{port}/")
    mkdocs_cmd = [
        sys.executable,
        "-m",
        "mkdocs",
        "serve",
        "--config-file",
        str(site_src / "mkdocs.yml"),
        "--dev-addr",
        f"{host}:{port}",
    ]
    # Start mkdocs serve in its own process group so Ctrl-C in our terminal
    # doesn't propagate twice and produce duplicate tracebacks. We wait on it
    # in a try/finally to guarantee cleanup.
    mkdocs_proc = subprocess.Popen(mkdocs_cmd, cwd=site_src)

    observer = None
    if not no_watch:
        typer.echo(f"Watching {book_dir / 'content'} and {book_file.name} for changes...")
        observer, _ = start_watcher(
            book_file=book_file,
            book_dir=book_dir,
            site_src=site_src,
            on_report=_watcher_report_callback,
            sandbox_override=sandbox,
        )

    try:
        mkdocs_proc.wait()
    except KeyboardInterrupt:
        typer.echo("\nShutting down...")
    finally:
        if observer is not None:
            observer.stop()
            observer.join(timeout=2)
        if mkdocs_proc.poll() is None:
            mkdocs_proc.terminate()
            try:
                mkdocs_proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                mkdocs_proc.kill()


def _report_build(report) -> None:
    """Print preprocessor warnings/errors from a BuildReport."""
    for warn in report.warnings:
        typer.echo(f"  warning: {warn}", err=True)
    for err in report.errors:
        typer.echo(f"  error: {err}", err=True)


def _summarise_report(report) -> str:
    """Compact one-liner describing a BuildReport's pages + cache + precompute stats."""
    parts = [f"{report.pages} pages"]
    if report.pages_cached or report.pages_rendered:
        parts.append(f"{report.pages_rendered} rendered, {report.pages_cached} cached")
    if report.widgets_precomputed or report.widgets_skipped:
        parts.append(f"{report.widgets_precomputed} precomputed, {report.widgets_skipped} skipped")
    return ", ".join(parts)


def _watcher_report_callback(report) -> None:
    """Called by the watcher after each rebuild. Logs result; never raises."""
    if report.ok:
        typer.echo(f"  rebuilt ({_summarise_report(report)})")
    else:
        typer.echo("  rebuild failed:", err=True)
        _report_build(report)


@app.command("check")
def check(
    book_file: Path = typer.Option(
        Path("book.yml"),
        "--book",
        "-b",
        help="Path to the book.yml config.",
        exists=True,
        dir_okay=False,
    ),
    strict: bool = typer.Option(
        False,
        "--strict",
        help="Fail on warnings.",
    ),
) -> None:
    """Validate ``book.yml`` and linked content without building."""
    book = _load_or_exit(book_file)
    typer.echo(f"OK: loaded '{book.title}' with {_count_toc(book.toc)} TOC entries")
    if strict:
        typer.echo("[stub] --strict content checks not yet implemented")


@app.command("sync-deps")
def sync_deps(
    book_file: Path = typer.Option(
        Path("book.yml"),
        "--book",
        "-b",
        help="Path to the book.yml config.",
        exists=True,
        dir_okay=False,
    ),
    check: bool = typer.Option(
        False,
        "--check",
        help=(
            "Don't modify any files. Exit non-zero if any notebook would have "
            "its PEP 723 block updated. Suitable for a CI hook."
        ),
    ),
) -> None:
    """Write or refresh PEP 723 ``# /// script`` blocks in TOC ``.py`` notebooks.

    Walks every notebook entry in ``book.yml``'s TOC, derives its
    dependency list (AST-walks imports, maps to PyPI distributions
    via marimo's table, applies ``dependencies.extras`` and
    ``dependencies.overrides``), and updates the file's PEP 723 block
    in place.

    Existing blocks are *merged* rather than overwritten — any
    ``requires-python``, ``tool.uv`` table, or hand-curated dependency
    that's already there is preserved; new dependencies are added.
    Run this before sharing a notebook with molab or pushing to a
    repo whose CI builds in WASM mode, so the block lands in version
    control instead of only existing in build output.

    With ``--check``, the command leaves files unchanged and exits
    code 1 if any notebook is missing or out-of-date relative to its
    detected imports + ``book.yml``'s ``dependencies`` config.
    """
    from .preprocessor import _iter_file_entries, _running_python_version_constraint

    book = _load_or_exit(book_file)
    book_dir = book_file.resolve().parent
    deps_cfg = book.dependencies
    requires_python = deps_cfg.requires_python or _running_python_version_constraint()

    py_entries = [e for e in _iter_file_entries(book.toc) if e.file.suffix == ".py"]
    if not py_entries:
        typer.echo("No marimo .py notebooks in TOC.")
        return

    changed: list[Path] = []
    skipped: list[Path] = []

    for entry in py_entries:
        src_abs = (book_dir / entry.file).resolve()
        if not src_abs.exists():
            typer.echo(f"  skip: {entry.file} (missing)", err=True)
            skipped.append(src_abs)
            continue
        before = src_abs.read_text(encoding="utf-8")
        deps = derive_dependencies(
            before,
            extras=deps_cfg.extras,
            overrides=deps_cfg.overrides,
            pin=deps_cfg.pin,
        )
        after = write_pep723_block(before, deps, requires_python=requires_python)
        if after == before:
            continue
        changed.append(src_abs)
        if check:
            typer.echo(f"  would update: {entry.file}")
        else:
            src_abs.write_text(after, encoding="utf-8")
            typer.echo(f"  updated: {entry.file}")

    if check and changed:
        typer.echo(
            f"sync-deps --check: {len(changed)} notebook(s) need updates.",
            err=True,
        )
        raise typer.Exit(code=1)
    if not changed:
        typer.echo(f"All {len(py_entries)} notebook(s) up to date.")
    else:
        verb = "would update" if check else "updated"
        typer.echo(f"sync-deps: {verb} {len(changed)} of {len(py_entries)} notebook(s).")


@app.command("clean")
def clean(
    book_file: Path = typer.Option(
        Path("book.yml"),
        "--book",
        "-b",
        help="Path to the book.yml config (used to locate the book directory).",
        exists=True,
        dir_okay=False,
    ),
    output: Path = typer.Option(
        Path("_site"),
        "--output",
        "-o",
        help="Output directory to remove (relative paths resolve against the book directory).",
    ),
) -> None:
    """Remove build artifacts (``_site/``, ``_site_src/``, cache)."""
    book_dir = book_file.resolve().parent
    site_dir = output.resolve() if output.is_absolute() else (book_dir / output).resolve()
    targets = [
        site_dir,
        book_dir / "_site_src",
        book_dir / ".marimo_book_cache",
    ]
    removed = 0
    for t in targets:
        if t.is_dir():
            shutil.rmtree(t)
            typer.echo(f"  removed {t}")
            removed += 1
    if removed == 0:
        typer.echo("Nothing to clean.")
    else:
        typer.echo(f"Cleaned {removed} directorie(s).")


# --- helpers -----------------------------------------------------------------


def _load_or_exit(path: Path):
    """Load a book.yml and exit with a friendly error if it fails validation."""
    try:
        return load_book(path)
    except ValidationError as e:
        typer.echo(f"error: invalid {path}:", err=True)
        typer.echo(str(e), err=True)
        raise typer.Exit(code=2) from None
    except FileNotFoundError:
        typer.echo(f"error: {path} not found", err=True)
        raise typer.Exit(code=2) from None


def _count_toc(toc) -> int:
    """Count leaf entries (files + urls) in a TOC, recursively."""
    count = 0
    for entry in toc:
        if hasattr(entry, "children"):
            count += _count_toc(entry.children)
        else:
            count += 1
    return count


if __name__ == "__main__":
    app()
