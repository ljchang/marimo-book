"""Inject per-page launch buttons (molab, GitHub, download).

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


def render_button_row(book: Book, source_file: Path, *, repo_subpath: str = "") -> str:
    """Return an HTML string with a row of enabled launch buttons.

    Returns an empty string if none are enabled for this page.

    ``repo_subpath`` is the path from the repo root to the book root,
    posix-style, with no trailing slash (e.g. ``"docs"`` when the book
    lives at ``docs/`` in the repo). It's prepended to the source path
    in every URL so the GitHub / molab / raw-download links resolve to
    the actual file. Empty when the book lives at the repo root (the
    typical case — most consumers run ``marimo-book`` against a
    book.yml at the repo top level).
    """
    buttons: list[str] = []
    source_posix = source_file.as_posix()
    if repo_subpath:
        source_posix = f"{repo_subpath.strip('/')}/{source_posix}"

    if book.launch_buttons.molab and source_file.suffix == ".py":
        url = _molab_url(book, source_posix)
        if url:
            buttons.append(
                _button(
                    "marimo-book-button marimo-book-button-molab",
                    url,
                    "Open in molab",
                    title="Open and run this notebook in molab",
                    icon=_ICON_MARIMO,
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
    inner = icon + f'<span class="marimo-book-button-label">{text}</span>'
    return f"<a {' '.join(attrs)}>{inner}</a>"


# --- Icons --------------------------------------------------------------------
#
# Inlined SVG, filled with ``currentColor`` so each glyph takes the palette's
# foreground on either theme. GitHub's and the download arrow are Material
# Symbols; the molab button carries marimo's own mark.

# marimo's mark — the sketched circle from its logotype (marimo-team/marimo,
# docs/_static/marimo-logotype-thick.svg), lifted out of the lock-up and given
# a tight viewBox. Coordinates are rounded to one decimal place: that is
# indistinguishable at the 24 px this renders at and nearly halves the payload.
# Rounding to integers is *not* safe — the path is relative, so the error
# accumulates into visibly fatter strokes.
#
# molab's own logo is a colour illustration rather than a glyph, so it cannot
# be a currentColor path and sat oddly beside the monochrome icons around it.
# The parent mark reads as the same family and matches the row.
_ICON_MARIMO = (
    '<svg class="marimo-book-button-icon" viewBox="487.8 369.1 224.42 231.84" '
    'aria-hidden="true" focusable="false">'
    '<path d="m 517.4,413.6 c 1.5,-1.8 3.2,-4.2 2.1,-6.3 6,-3.6 11.4,-8.3 15.8,-13.8 -2.4,1.9 -5,3.4 -7.7,4.6 20.7,-20.4 51.8,-29.7 80.3,-24 -23,-0.9 -46.4,5.2 -65.4,18.2 -19.1,12.9 -33.5,32.7 -39.1,55.1 8.4,-24.5 26.2,-45.6 48.9,-58 -1.8,1.8 -3.6,3.7 -5.4,5.6 8.6,-3.6 16.5,-8.9 25,-12.6 25.2,-11 55.5,-6.9 79,7.5 23.5,14.4 40.4,37.9 50.2,63.6 4.3,11.2 7.3,23.7 3.5,35.1 -0.9,-14.8 -5.7,-29.1 -12,-42.6 -10.5,-22.4 -25.5,-43.4 -46.6,-56.2 -21.1,-12.8 -49,-16.2 -70.6,-4.2 11.1,-1.2 22.2,-1.8 33.2,-0.3 20.6,2.9 39.7,13.7 54.1,28.7 14.4,15 24.4,34 30.3,53.9 5.7,19.5 7.6,41 0.3,60 21.4,-34.7 17.9,-82.9 -8.3,-114.1 -11,-13 -25.2,-23 -40.5,-30.2 -17.7,-8.3 -37.1,-13.1 -56.7,-12.6 -19.5,0.5 -39.1,6.6 -54.7,18.4 13,-11.4 29.8,-17.9 47,-19.7 17.2,-1.7 34.7,1.1 51,6.6 34,11.6 65,37 75,71.5 2.5,8.9 3.7,18 4.7,27.2 0.9,7.9 1.6,15.9 1.4,23.9 -0.8,39.5 -26,78 -62.7,92.4 -10.4,4.1 -21.4,6.3 -32.5,7.8 -17.7,2.5 -36.1,3.2 -53.1,-2.1 -8.8,-2.8 -17,-7 -24.6,-12.3 -31.5,-21.6 -51.4,-59.2 -51.4,-97.4 0,-6.8 0.6,-13.5 1.5,-20.2 0.8,-6.2 1.9,-12.3 3.7,-18.2 2.7,-8.7 6.9,-17 12.5,-24.3 1,-0.6 1.9,-1.2 2.9,-1.9 -12.8,27 -20.4,59 -8.7,86.6 -4.2,-18 -4.5,-36.8 -0.8,-54.8 1.2,-0.4 2.4,-0.9 3.5,-1.4 0.1,-1.2 0.1,-2.3 0.2,-3.5 -0.9,1 -1.7,1.9 -2.5,2.9 2,-14.3 8.1,-27.9 17.4,-38.8 m 8.7,-0.7 c 3.3,-2.3 6.7,-4.5 10,-6.8 -2.1,4.3 -6,7.6 -10.5,9.1 -21.1,21.8 -27.5,54.2 -25,84.3 1,11.4 3.3,23.2 10.6,32 -5.1,-21.1 -5.4,-43.3 -0.7,-64.5 0.9,-0.1 1.2,1.1 1.2,2.1 0.4,14.2 -2.1,28.4 -1,42.6 1,14.1 6.3,29.1 18.2,36.8 9.3,6 18.5,12.1 27.7,18.1 -21.6,-6.9 -40.4,-21.9 -52.1,-41.3 3.1,8.5 7.5,16.5 12.9,23.8 -0.7,-1.9 -1.3,-3.9 -2.1,-5.9 5.5,5.1 11,10.1 16.4,15.2 4,3.7 10.3,7.5 14.4,3.9 0.6,1.4 -0.5,3 -2,3.4 -1.5,0.4 -3,0 -4.5,-0.4 6.5,4.7 13.3,9 20.3,13 -1,0.2 -1.3,1.7 -0.7,2.5 0.6,0.9 1.7,1.1 2.8,1.4 25.8,5.6 53.2,3.5 77.8,-6 -21.2,5 -43.7,6.1 -64.2,-1.1 -17.3,-6 -32.5,-18 -42.4,-33.4 -3.2,-5 -5.8,-10.2 -8.3,-15.5 -7.8,-17.6 -12.8,-36.8 -11.4,-56 1.4,-19.2 9.8,-38.4 24.9,-50.3 1.6,-1.2 3.5,-2.4 5.4,-1.9 -14.9,10.8 -23.8,28.7 -26.1,46.9 -2.3,18.3 1.5,36.9 8.1,54 4.8,12.1 11.1,23.9 19.8,33.6 3.7,4.2 7.9,7.9 12.7,10.8 8.8,5.3 19.2,7.3 29.4,8.6 13.9,1.8 27.9,2.5 41.8,2.2 -17.7,4.2 -36.1,1.2 -54,-1.8 30.3,11.4 65.9,4.4 92,-14.7 5.2,-3.8 10.1,-8.1 14,-13.2 6,-7.9 9.7,-17.5 11.5,-27.3 4.8,-25.5 -2.1,-52.1 -14.4,-74.9 -8.6,-15.9 -20,-30.6 -35,-40.5 -14,-9.3 -30.7,-14.2 -47.5,-15.1 -25.8,-1.5 -53.1,7 -70.3,26.4 M 576.8,588.2 c 11.6,2.9 23.3,5 35.2,6.4 -14.6,3.3 -29.6,-1.8 -43.7,-6.8 -8.3,-2.9 -16.7,-5.9 -24.5,-10.3 -18.7,-10.4 -32.7,-28.1 -40.9,-47.9 -1.4,-3.5 -2.7,-7 -3.8,-10.6 -0.1,-0.4 -0.4,0.6 0,0.4 0.4,-0.2 0.4,-0.8 0.2,-1.2 -4.9,-11.7 -7.8,-24.3 -8.7,-36.9 -0.9,19.1 3.8,38.3 12.5,55.4 9.4,18.6 23.5,35 41.2,46 17.7,11.1 38.9,16.7 59.6,14.7 29.1,-2.9 54.7,-19.9 78.2,-37.3 -10.4,13.7 -26.1,22.2 -41.3,30.2 26.4,-7.4 47.6,-28.3 60.3,-52.6 -6.3,10.8 -16.2,19.3 -26.9,25.6 -10.8,6.4 -22.6,10.8 -34.4,15.1 -5.2,1.9 -10.4,3.7 -15.8,5.2 -15.3,4.4 -31.4,5.9 -47.2,4.5 m 108,-36.5 c 2.7,-2.5 5.3,-5.1 7.5,-8 3.4,-4.7 5.7,-10.1 7.8,-15.5 2.9,-7.3 5.9,-14.7 6.6,-22.6 -1.4,1.2 -1.9,3.1 -2.4,4.9 -7.2,24.9 -24.9,46.6 -48,58.5 10.9,-2.4 20.2,-9.5 28.4,-17.1 m -131.9,26.4 c 1.1,0.3 2.5,0.8 2.6,1.9 0.4,-0.8 1.7,-0.8 2.2,0 0.2,-0.1 0.1,-0.4 -0.2,-0.5 -1.6,-0.9 -3.2,-1.7 -4.8,-2.6 -6.5,-3.5 -12.5,-7.9 -17.9,-13 -0.6,1.4 -0.2,3.2 1.1,4 2.4,1.7 4.8,3.5 7.1,5.2 2.9,2.4 6.3,4.1 9.9,5 m 155.9,-81.6 c -0.2,4 -0.4,8 -0.7,12 -0.1,0.5 -0.1,1.1 -0.1,1.6 -0.1,1 -0.1,1.9 -0.2,2.9 -0.1,1.2 -0.1,2.3 -0.1,3.5 2.3,-9.2 3.1,-18.8 2.4,-28.2 -0.3,-0.1 -0.5,-0.3 -0.8,-0.4 -0.2,2.9 -0.4,5.7 -0.5,8.6 m -209.8,-59.2 c -0.4,0.7 -0.7,1.4 -1,2.1 0.4,0.5 1.1,-0.1 1.2,-0.7 0.2,-0.5 0.3,-1.3 0.9,-1.3 -0.3,-0.3 -0.5,-0.5 -0.8,-0.8 -0.1,0.2 -0.2,0.5 -0.1,0.8 m 39,-44.8 c 0.5,-0.4 1.1,-0.9 1.6,-1.3 -0.9,-0.4 -2.1,0.1 -2.5,1.1 0.3,0.1 0.5,0.2 0.9,0.3 m 1.7,-2.5 c 1.2,0.3 2.5,-0.1 3.5,-0.9 -1.2,-0.1 -2.5,0.2 -3.5,0.9 m -43,54.8 c -0.1,-0.3 -0.1,-0.5 -0.1,-0.8 -1,0.4 -1.5,1.8 -0.9,2.7 0.2,-0.7 0.5,-1.3 1,-1.9 m -6.1,27.5 c -0.3,0.4 -0.1,1 0.4,1.1 0.3,-0.9 0.2,-1.8 -0.1,-2.7 -0.5,0.3 -0.7,1 -0.4,1.5"/></svg>'
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
