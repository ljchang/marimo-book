"""Small transforms applied to hand-authored Markdown files.

v0.1 only needs two, driven by the dartbrains syntax inventory:

- ``{download}`label <path>``` — rewritten to a plain Markdown link. Material
  serves the linked file as a static asset; no special role handling
  required by the shell.
- ``:::{glossary}`` fenced blocks — fencing stripped. The contents are
  definition-list markdown that Material renders natively (via ``def_list``).
"""

from __future__ import annotations

import re


_DOWNLOAD_RE = re.compile(
    r"""
    \{download\}                   # role marker
    `
    \s*                            # optional whitespace
    ([^`<]*?)                      # link text (group 1), may be empty
    \s*
    <([^`>]+)>                     # target path (group 2)
    \s*
    `
    """,
    re.VERBOSE,
)


def rewrite_download_roles(markdown: str) -> str:
    """Convert ``{download}`text <path>``` → ``[text](path)``.

    If the text is empty (``{download}` <foo.pdf>``` seen in some dartbrains
    pages), the filename is used as the link text.
    """

    def sub(match: re.Match) -> str:
        text = match.group(1).strip()
        target = match.group(2).strip()
        if not text:
            # Use the filename as the link label.
            text = target.rsplit("/", 1)[-1]
        return f"[{text}]({target})"

    return _DOWNLOAD_RE.sub(sub, markdown)


_GLOSSARY_OPEN_RE = re.compile(r"^:::\{glossary\}\s*$", re.MULTILINE)
_GLOSSARY_CLOSE_RE = re.compile(r"^:::\s*$", re.MULTILINE)


def strip_glossary_fences(markdown: str) -> str:
    """Remove ``:::{glossary}`` opening and matching ``:::`` closing fences.

    The inner definition-list content is left intact. Material renders
    ``term\\n: definition`` natively when ``def_list`` is enabled in
    ``markdown_extensions``.
    """
    lines = markdown.split("\n")
    out: list[str] = []
    in_block = False
    for line in lines:
        if _GLOSSARY_OPEN_RE.match(line):
            in_block = True
            continue
        if in_block and _GLOSSARY_CLOSE_RE.match(line):
            in_block = False
            continue
        out.append(line)
    return "\n".join(out)


def apply_md_transforms(markdown: str) -> str:
    """Apply all v0.1 Markdown transforms in order."""
    markdown = rewrite_download_roles(markdown)
    markdown = strip_glossary_fences(markdown)
    return markdown
