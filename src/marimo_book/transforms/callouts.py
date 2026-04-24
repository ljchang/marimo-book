"""Translate ``<marimo-callout-output>`` custom elements into static HTML.

Marimo renders callouts at runtime via a custom element. Our static site
doesn't load the marimo frontend, so we parse the element's attributes and
re-emit a Material for MkDocs admonition (which ``pymdownx.blocks.admonition``
styles identically across light and dark themes).
"""

from __future__ import annotations

import html
import json
import re

from bs4 import BeautifulSoup

# Marimo's callout kinds → Material admonition types.
# Material supports: note, abstract, info, tip, success, question, warning,
# failure, danger, bug, example, quote.
_KIND_MAP = {
    "info": "info",
    "note": "note",
    "success": "success",
    "tip": "tip",
    "warn": "warning",
    "warning": "warning",
    "danger": "danger",
    "error": "failure",
    "neutral": "note",
}


def render_callout_html(raw_html: str) -> str | None:
    """Return Material admonition HTML for a ``<marimo-callout-output>``.

    Returns ``None`` if the input is not a recognizable callout output — the
    caller should then pass the raw HTML through.
    """
    soup = BeautifulSoup(raw_html, "lxml")
    node = soup.find("marimo-callout-output")
    if node is None:
        return None

    kind = _decode_attr(node.get("data-kind", "info")) or "info"
    body_html = _decode_attr(node.get("data-html", "")) or ""

    admon_type = _KIND_MAP.get(kind.lower(), "note")

    # The body is the marimo-rendered HTML for the callout's content — a
    # <span class="markdown prose..."> wrapper around either a rendered
    # markdown string (for mo.md(...)) or an arbitrary mo.Html block.
    body_inner = _strip_marimo_prose_wrapper(body_html).strip()

    # Emit pymdown-extensions "blocks" admonition syntax, which survives
    # Material's search indexer and renders identically under the slate
    # theme. The block-level form is more robust than the inline ``!!!``
    # form when the body contains HTML or multiple paragraphs.
    return (
        f'<div class="admonition {admon_type} marimo-book-callout">\n'
        f"{body_inner}\n"
        "</div>"
    )


# --- helpers -----------------------------------------------------------------


def _decode_attr(raw: str) -> str:
    """Decode a marimo ``data-*`` attribute.

    The attribute is HTML-encoded *and* JSON-encoded (because the custom
    element expects JSON-like values). We unescape entities then try
    ``json.loads``; fall back to the raw string if that fails.
    """
    if raw is None:
        return ""
    unescaped = html.unescape(raw)
    try:
        value = json.loads(unescaped)
    except (json.JSONDecodeError, ValueError):
        value = unescaped
    return value if isinstance(value, str) else str(value)


_PROSE_RE = re.compile(
    r'^<span\s+class="markdown prose[^"]*contents">(.*)</span>$',
    re.DOTALL,
)


def _strip_marimo_prose_wrapper(body: str) -> str:
    """Remove the outer ``<span class="markdown prose ...">`` wrapper if present.

    Marimo wraps markdown-rendered content in a span with Tailwind-style
    classes that don't exist in our theme. Strip the outer wrapper but keep
    nested ones in case they were deliberately authored.
    """
    match = _PROSE_RE.match(body.strip())
    if match:
        inner = match.group(1)
        # Flatten a single nested "paragraph" span — marimo adds this for
        # mo.md() results. More deeply nested ones stay.
        inner = re.sub(
            r'^<span\s+class="paragraph">(.*)</span>$',
            r"\1",
            inner.strip(),
            flags=re.DOTALL,
        )
        return inner
    return body
