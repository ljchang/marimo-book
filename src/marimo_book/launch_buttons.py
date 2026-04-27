"""Inject per-page launch buttons (molab, GitHub, download, print).

The preprocessor calls :func:`render_button_row` with a ``book.yml`` config
and the relative path of the source file inside the book (e.g.
``content/GLM.py``). Enabled buttons appear as a row at the top of each
rendered page; when ``launch_buttons.placement: header``, a small JS shim
in marimo_book.js relocates the row into Material's header bar. Button
markup is plain HTML + inline SVG so zensical renders identical output
when we port in v0.3.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

from .config import Book


def render_button_row(book: Book, source_file: Path) -> str:
    """Return an HTML string with a row of enabled launch buttons.

    Returns an empty string if none are enabled for this page.
    """
    buttons: list[str] = []
    source_posix = source_file.as_posix()

    if book.launch_buttons.molab and source_file.suffix == ".py":
        url = _molab_url(book, source_posix)
        if url:
            buttons.append(
                _button(
                    "marimo-book-button marimo-book-button-molab",
                    url,
                    "Open in molab",
                    title="Open and run this notebook in molab",
                    icon=_ICON_ROCKET,
                )
            )

    if book.launch_buttons.github:
        url = _github_url(book, source_posix)
        if url:
            buttons.append(
                _button(
                    "marimo-book-button marimo-book-button-github",
                    url,
                    "View on GitHub",
                    title="View the source on GitHub",
                    icon=_ICON_GITHUB,
                )
            )

    if book.launch_buttons.download and source_file.suffix == ".py":
        url = _raw_url(book, source_posix)
        if url:
            buttons.append(
                _button(
                    "marimo-book-button marimo-book-button-download",
                    url,
                    "Download .py",
                    title="Download the marimo notebook source",
                    download=source_file.name,
                    icon=_ICON_DOWNLOAD,
                )
            )

    if book.launch_buttons.print:
        # Print/Save-as-PDF: a button with `data-marimo-book-print` that
        # marimo_book.js binds to window.print(). Browsers' print dialog
        # offers "Save as PDF" so users get a per-page PDF without
        # configuring mkdocs-with-pdf.
        buttons.append(
            _print_button(
                "Print / save PDF",
                "Print this chapter or save it as a PDF",
            )
        )

    if not buttons:
        return ""
    return (
        '<div class="marimo-book-buttons" data-placement="'
        + book.launch_buttons.placement
        + '">\n'
        + "\n".join(buttons)
        + "\n</div>"
    )


# --- URL builders ------------------------------------------------------------


def _molab_url(book: Book, source_posix: str) -> str | None:
    owner_repo = _owner_repo(book.repo)
    if owner_repo is None:
        return None
    owner, repo = owner_repo
    return f"https://molab.marimo.io/github/{owner}/{repo}/blob/{book.branch}/{source_posix}"


def _github_url(book: Book, source_posix: str) -> str | None:
    if not book.repo:
        return None
    return f"{book.repo.rstrip('/')}/blob/{book.branch}/{source_posix}"


def _raw_url(book: Book, source_posix: str) -> str | None:
    owner_repo = _owner_repo(book.repo)
    if owner_repo is None:
        return None
    owner, repo = owner_repo
    return f"https://raw.githubusercontent.com/{owner}/{repo}/{book.branch}/{source_posix}"


def _owner_repo(repo_url: str | None) -> tuple[str, str] | None:
    if not repo_url:
        return None
    parsed = urlparse(repo_url)
    if "github.com" not in parsed.netloc:
        return None
    parts = [p for p in parsed.path.split("/") if p]
    if len(parts) < 2:
        return None
    return parts[0], parts[1].removesuffix(".git")


# --- HTML helpers ------------------------------------------------------------


def _button(
    css_class: str,
    href: str,
    text: str,
    *,
    title: str | None = None,
    download: str | None = None,
    icon: str = "",
) -> str:
    attrs = [
        f'class="{css_class}"',
        f'href="{href}"',
        'target="_blank"',
        'rel="noopener"',
        f'aria-label="{title or text}"',
    ]
    if title:
        attrs.append(f'title="{title}"')
    if download is not None:
        attrs.append(f'download="{download}"')
    inner = (
        icon
        + f'<span class="marimo-book-button-label">{text}</span>'
    )
    return f"<a {' '.join(attrs)}>{inner}</a>"


def _print_button(text: str, title: str) -> str:
    """A button bound to window.print() by marimo_book.js."""
    attrs = [
        'class="marimo-book-button marimo-book-button-print"',
        'href="#"',
        'data-marimo-book-print',
        f'title="{title}"',
        f'aria-label="{title}"',
    ]
    inner = (
        _ICON_PRINT
        + f'<span class="marimo-book-button-label">{text}</span>'
    )
    return f"<a {' '.join(attrs)}>{inner}</a>"


# --- Icons (Material Symbols, inlined as SVG) ---------------------------------

_ICON_ROCKET = (
    '<svg class="marimo-book-button-icon" viewBox="0 0 24 24" '
    'aria-hidden="true" focusable="false">'
    '<path d="M9.19 6.35c-2.04 2.29-3.44 5.58-3.57 5.89L2 10.69l4.05-4.05c'
    ".47-.47 1.15-.68 1.81-.55l1.33.26zm5.55 10.7c.49-.49 5.16-2.4 5.16-2.4l"
    "-1.55 1.55c-.47.47-1.15.68-1.81.55l-1.33-.26-.47.56zM21.39 11.13c-.79 1"
    "1.6-3.06 14.65-5.65 14.79-1.78.1-3.05-1.39-3.21-1.59L8.92 13.6 5.49 11"
    ".27 4.4 9.14C5.05 8.5 5.49 8.05 6 7.66l1.74 1.61c.42.39.39 1.05-.06 1"
    ".42-.45.36-1.13.34-1.55-.05L4 8.14c.46-.61.99-1.21 1.62-1.81 5.4-5.4 9"
    '.62-4.5 10.57-4.21.95.3 1.84 4.52-3.56 9.92z"/>'
    "</svg>"
)

_ICON_GITHUB = (
    '<svg class="marimo-book-button-icon" viewBox="0 0 24 24" '
    'aria-hidden="true" focusable="false">'
    '<path d="M12 .3a12 12 0 0 0-3.79 23.4c.6.11.82-.26.82-.58v-2.05c-3.34.7'
    "2-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.08-.74.08-.73.08-"
    ".73 1.2.09 1.83 1.24 1.83 1.24 1.07 1.84 2.81 1.31 3.5 1 .11-.78.42-1."
    "31.76-1.61-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.46-2.38 1.24-3.22-.13-.3"
    "1-.54-1.53.11-3.18 0 0 1.01-.32 3.31 1.23a11.5 11.5 0 0 1 6 0c2.31-1.5"
    "5 3.31-1.23 3.31-1.23.66 1.65.25 2.87.13 3.18.77.84 1.24 1.91 1.24 3.2"
    "2 0 4.61-2.81 5.62-5.49 5.92.42.36.81 1.1.81 2.22v3.29c0 .32.21.69.83."
    '58A12 12 0 0 0 12 .3"/>'
    "</svg>"
)

_ICON_DOWNLOAD = (
    '<svg class="marimo-book-button-icon" viewBox="0 0 24 24" '
    'aria-hidden="true" focusable="false">'
    '<path d="M5 20h14v-2H5v2zM19 9h-4V3H9v6H5l7 7 7-7z"/>'
    "</svg>"
)

_ICON_PRINT = (
    '<svg class="marimo-book-button-icon" viewBox="0 0 24 24" '
    'aria-hidden="true" focusable="false">'
    '<path d="M19 8H5c-1.66 0-3 1.34-3 3v6h4v4h12v-4h4v-6c0-1.66-1.34-3-3-3'
    "zm-3 11H8v-5h8v5zm3-7c-.55 0-1-.45-1-1s.45-1 1-1 1 .45 1 1-.45 1-1 1z"
    'm-1-9H6v4h12V3z"/>'
    "</svg>"
)
