"""Inject per-page launch buttons (molab, GitHub, download).

The preprocessor calls :func:`render_button_row` with a ``book.yml`` config
and the relative path of the source file inside the book (e.g.
``content/GLM.py``). Enabled buttons appear as a small row of links at the
top of each rendered page. Button markup is plain HTML so zensical will
render the same row verbatim when we port in v0.3.
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
                )
            )

    if not buttons:
        return ""
    return '<div class="marimo-book-buttons">\n' + "\n".join(buttons) + "\n</div>"


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
) -> str:
    attrs = [f'class="{css_class}"', f'href="{href}"', 'target="_blank"', 'rel="noopener"']
    if title:
        attrs.append(f'title="{title}"')
    if download is not None:
        attrs.append(f'download="{download}"')
    return f"<a {' '.join(attrs)}>{text}</a>"
