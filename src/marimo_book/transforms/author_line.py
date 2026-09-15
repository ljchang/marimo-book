"""Strip the byline a notebook writes under its title (``defaults.hide_author_line``).

Chapters conventionally open with the page title and an italic byline::

    # Introduction to Pandas
    *Written by Luke Chang & Jin Cheong*

``book.yml``'s ``authors:`` already renders author information into the page
header, so a book can drop the in-page repeat with ``hide_author_line: true``
(the default). Only the *first* such line on a page is removed — a byline
quoted later in the prose survives.

Two shapes have to be handled, because a page's prose reaches us as either:

markdown
    The ordinary path: a plain ``mo.md(...)`` cell is converted to Markdown, so
    the byline is a literal ``*Written by ...*`` line.
marimo's HTML
    A composite output — ``mo.vstack([mo.md(...), mo.image(...)])`` — is
    rendered by marimo itself, which emits the byline as
    ``<span class="paragraph"><em>Written by ...</em></span>``.

WASM pages are handled earlier, in :mod:`marimo_book.transforms.wasm`, by
editing the staged source the islands runtime executes: their prose is
re-rendered in the browser from the islands payload, so a body-level strip
would reappear the moment Pyodide finished booting.
"""

from __future__ import annotations

import re

# "Written by", "written By:", "Written By :" — the colon and case vary across
# books; the emphasis markers do too (``*…*`` and ``_…_`` both occur).
_BYLINE_TEXT = r"written\s+by\b"

_MARKDOWN_BYLINE_RE = re.compile(rf"(?im)^[ \t]*(\*|_)\s*{_BYLINE_TEXT}.*?\1[ \t]*$\n?")

# marimo's rendering of the same line. The emphasis element wraps the whole
# paragraph, which is what distinguishes a byline from prose that merely
# mentions an author.
_HTML_BYLINE_RE = re.compile(
    rf"(?is)<(span class=\"paragraph\"|p)>\s*<em>\s*{_BYLINE_TEXT}.*?</em>\s*</(?:span|p)>\s*"
)


def strip_markdown_author_line(markdown: str) -> str:
    """Drop the first italic ``Written by …`` line from Markdown prose."""
    return _MARKDOWN_BYLINE_RE.sub("", markdown, count=1)


def strip_html_author_line(html: str) -> str:
    """Drop the first fully-italic ``Written by …`` paragraph from marimo's HTML."""
    return _HTML_BYLINE_RE.sub("", html, count=1)


def strip_author_line(body: str) -> str:
    """Remove the page's byline in whichever of the two shapes it arrived in.

    Tries the Markdown form first; if the body carried none (a composite cell,
    or a page with no byline at all) the HTML form is tried. At most one line
    is removed either way.
    """
    stripped = strip_markdown_author_line(body)
    if stripped != body:
        return stripped
    return strip_html_author_line(body)
