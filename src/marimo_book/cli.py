"""``marimo-book`` command-line interface.

All commands are dispatched through the Typer ``app`` object. Commands are
stubs in v0.1.0.dev0 and will be fleshed out as the preprocessor and shell
generator land.
"""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

import shutil
import subprocess
import sys

from marimo_book import __version__
from marimo_book.config import load_book
from marimo_book.preprocessor import Preprocessor

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
    example: str = typer.Option(
        "minimal",
        "--example",
        help="Scaffold template to use (currently only 'minimal').",
    ),
) -> None:
    """Scaffold a new book in ``DIRECTORY``."""
    typer.echo(f"[stub] marimo-book new {directory} (example={example})")
    raise typer.Exit(code=1)


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
) -> None:
    """Build the static site from ``book.yml``."""
    book = _load_or_exit(book_file)
    book_dir = book_file.resolve().parent
    site_src = book_dir / "_site_src"
    site_dir = Path(output).resolve() if output.is_absolute() else (book_dir / output).resolve()

    if clean:
        for target in (site_src, site_dir):
            if target.exists():
                shutil.rmtree(target)

    typer.echo(f"Preprocessing '{book.title}' ({_count_toc(book.toc)} pages)...")
    pre = Preprocessor(book, book_dir=book_dir)
    report = pre.build(out_dir=site_src, site_dir=site_dir)

    for warn in report.warnings:
        typer.echo(f"  warning: {warn}", err=True)
    for err in report.errors:
        typer.echo(f"  error: {err}", err=True)
    if not report.ok:
        typer.echo(f"Preprocessing failed ({len(report.errors)} errors).", err=True)
        raise typer.Exit(code=1)
    typer.echo(f"Preprocessing OK ({report.pages} pages staged at {site_src}).")

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

    typer.echo(f"Preprocessing '{book.title}' ({_count_toc(book.toc)} pages)...")
    pre = Preprocessor(book, book_dir=book_dir)
    report = pre.build(out_dir=site_src)
    _report_build(report)
    if not report.ok:
        raise typer.Exit(code=1)
    typer.echo(f"Preprocessing OK ({report.pages} pages staged at {site_src}).")

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


def _watcher_report_callback(report) -> None:
    """Called by the watcher after each rebuild. Logs result; never raises."""
    if report.ok:
        typer.echo(f"  rebuilt ({report.pages} pages)")
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
    typer.echo(
        f"OK: loaded '{book.title}' with {_count_toc(book.toc)} TOC entries"
    )
    if strict:
        typer.echo("[stub] --strict content checks not yet implemented")


@app.command("clean")
def clean(
    output: Path = typer.Option(
        Path("_site"),
        "--output",
        "-o",
        help="Output directory to remove.",
    ),
) -> None:
    """Remove build artifacts (``_site/``, ``_site_src/``, cache)."""
    typer.echo(f"[stub] marimo-book clean (output={output})")
    raise typer.Exit(code=1)


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
