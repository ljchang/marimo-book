"""Content-level link rewrites applied to both Markdown and marimo output.

Two small fixes that pay off across the whole book:

- ``rewrite_ipynb_links`` rewrites ``[text](Foo.ipynb)`` → ``[text](Foo.md)``
  when ``Foo.md`` exists among the staged pages. After the marimo-book
  preprocessor converts ``.py`` → ``.md``, any in-notebook prose that linked
  to a sibling as ``Connectivity.ipynb`` would otherwise 404.
- ``rewrite_parent_image_paths`` rewrites ``(../images/...)`` → ``(images/...)``
  when a content file originally at ``content/foo.md`` referenced
  ``../images/bar.pdf`` to reach a sibling at repo-root ``images/bar.pdf``.
  Once we flatten ``content/*.md`` into ``docs/*.md`` (with ``docs/images/``
  beside it), the ``../`` is wrong — mkdocs even suggests the fix in its
  warning text.

Both transforms are regex-based, safe on HTML, and idempotent.
"""

from __future__ import annotations

import re


# ``[text](target)`` where target is an in-tree ``.ipynb`` reference (not an
# absolute URL and not a fragment-only link). Captures the text, path, and
# trailing fragment/query so we can stitch the replacement back together.
_IPYNB_LINK_RE = re.compile(
    r"""
    (?P<prefix>\]\()           # opening ]( of a Markdown link
    (?!https?://)              # skip absolute URLs
    (?!/)                      # skip root-relative paths
    (?P<path>[^)#?\s]+\.ipynb) # the .ipynb path
    (?P<suffix>[)#?])          # trailing )  #fragment  or ?query
    """,
    re.VERBOSE,
)


def rewrite_ipynb_links(markdown: str, md_basenames: set[str]) -> str:
    """Rewrite ``.ipynb`` cross-refs to ``.md`` when the target page exists.

    ``md_basenames`` is the set of page names (without extension, without
    directory) that the preprocessor staged. Links whose stem isn't in that
    set are left alone — they might be intentional references to an outside
    .ipynb (e.g. downloadable examples).
    """

    def sub(match: re.Match) -> str:
        path = match.group("path")
        # Strip any directory component for the basename test.
        stem = path.rsplit("/", 1)[-1][: -len(".ipynb")]
        if stem not in md_basenames:
            return match.group(0)
        new_path = path[: -len(".ipynb")] + ".md"
        return match.group("prefix") + new_path + match.group("suffix")

    return _IPYNB_LINK_RE.sub(sub, markdown)


# Matches ``](../images/...)``, ``]("../images/...")``, and the same patterns
# inside HTML attributes. The leading ``../`` becomes unnecessary once the
# content tree is flattened from ``content/X.md`` to ``docs/X.md`` sitting
# next to ``docs/images/``.
_PARENT_IMAGE_MD_RE = re.compile(
    r"""
    (?P<prefix>\]\()            # Markdown link opener  (
    \.\./images/                # ../images/
    """,
    re.VERBOSE,
)

_PARENT_IMAGE_HTML_RE = re.compile(
    r"""
    (?P<prefix>\b(?:src|href)\s*=\s*["'])  # src="  or  href='
    \.\./images/                            # ../images/
    """,
    re.VERBOSE,
)


def rewrite_parent_image_paths(markdown: str) -> str:
    """Rewrite ``../images/<path>`` → ``images/<path>`` in links and HTML attrs.

    Applied to both Markdown link syntax ``[alt](../images/foo.png)`` and raw
    HTML attributes ``src="../images/foo.png"`` / ``href="../images/..."``.
    """
    markdown = _PARENT_IMAGE_MD_RE.sub(lambda m: m.group("prefix") + "images/", markdown)
    markdown = _PARENT_IMAGE_HTML_RE.sub(
        lambda m: m.group("prefix") + "images/", markdown
    )
    return markdown


def apply_link_rewrites(markdown: str, *, md_basenames: set[str] | None = None) -> str:
    """Run every link-rewrite transform in sequence."""
    if md_basenames:
        markdown = rewrite_ipynb_links(markdown, md_basenames)
    markdown = rewrite_parent_image_paths(markdown)
    return markdown
