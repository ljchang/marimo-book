"""``marimo-book`` command-line interface.

All commands are dispatched through the Typer ``app`` object. Commands are
stubs in v0.1.0.dev0 and will be fleshed out as the preprocessor and shell
generator land.
"""

from __future__ import annotations

from pathlib import Path

import typer
from pydantic import ValidationError

from marimo_book import __version__
from marimo_book.config import load_book

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
    typer.echo(
        f"[stub] marimo-book build (book={book_file}, output={output}, "
        f"strict={strict}, clean={clean}) — loaded '{book.title}' with "
        f"{_count_toc(book.toc)} TOC entries"
    )
    raise typer.Exit(code=1)


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
) -> None:
    """Serve the book locally with live reload."""
    _load_or_exit(book_file)
    typer.echo(f"[stub] marimo-book serve (host={host}, port={port})")
    raise typer.Exit(code=1)


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
