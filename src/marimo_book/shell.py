"""Generate an ``mkdocs.yml`` from a :class:`~marimo_book.config.Book`.

The preprocessor writes content to ``_site_src/docs/`` and this module emits
``_site_src/mkdocs.yml`` alongside it. ``mkdocs build`` then produces
``_site/``.

Because zensical reuses ``mkdocs.yml`` verbatim (per
https://zensical.org/compatibility/), the same file drives both shells —
only the build command changes when we port in v0.3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from .config import Book, FileEntry, SectionEntry, UrlEntry


def emit_mkdocs_yml(
    book: Book,
    *,
    docs_dir: Path,
    site_dir: Path,
    out_path: Path,
    nav: list[dict | str] | None = None,
    extra_css: list[str] | None = None,
    extra_javascript: list[str] | None = None,
) -> None:
    """Write ``mkdocs.yml`` derived from ``book``."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    config = _build_config(
        book,
        docs_dir=docs_dir,
        site_dir=site_dir,
        nav=nav or _nav_from_toc(book.toc),
        extra_css=extra_css or [],
        extra_javascript=extra_javascript or [],
    )
    with out_path.open("w", encoding="utf-8") as f:
        yaml.safe_dump(config, f, sort_keys=False, default_flow_style=False)


def _build_config(
    book: Book,
    *,
    docs_dir: Path,
    site_dir: Path,
    nav: list,
    extra_css: list[str],
    extra_javascript: list[str],
) -> dict[str, Any]:
    cfg: dict[str, Any] = {
        "site_name": book.title,
        "docs_dir": str(docs_dir),
        "site_dir": str(site_dir),
    }
    if book.description:
        cfg["site_description"] = book.description
    if book.repo:
        cfg["repo_url"] = book.repo
        cfg["edit_uri"] = _edit_uri_from_repo(book.repo)
    if book.copyright:
        cfg["copyright"] = book.copyright

    cfg["theme"] = _theme_block(book)
    cfg["extra_css"] = ["stylesheets/extra.css", *extra_css]
    cfg["extra_javascript"] = [
        "https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js",
        "javascripts/mathjax.js",
        # marimo-book runtime shim — rehydrates <div class="marimo-book-anywidget">
        # mounts without requiring marimo's frontend runtime.
        {"path": "javascripts/marimo_book.js", "defer": True},
        *extra_javascript,
    ]

    cfg["markdown_extensions"] = _markdown_extensions()

    # Analytics
    if book.analytics.provider != "none" and book.analytics.property:
        cfg.setdefault("extra", {})
        cfg["extra"]["analytics"] = {
            "provider": book.analytics.provider,
            "property": book.analytics.property,
        }

    cfg["nav"] = nav
    return cfg


def _theme_block(book: Book) -> dict[str, Any]:
    palette_default: dict[str, Any] = {
        "scheme": "default",
        "toggle": {
            "icon": "material/weather-sunny",
            "name": "Switch to dark mode",
        },
    }
    palette_slate: dict[str, Any] = {
        "scheme": "slate",
        "toggle": {
            "icon": "material/weather-night",
            "name": "Switch to light mode",
        },
    }
    # Material reserves "primary" / "accent" for its palette names; we set
    # them to "custom" so our extra.css controls them via CSS variables.
    if book.theme.palette.primary:
        palette_default["primary"] = "custom"
        palette_slate["primary"] = "custom"
    if book.theme.palette.accent:
        palette_default["accent"] = "custom"
        palette_slate["accent"] = "custom"

    theme: dict[str, Any] = {
        "name": "material",
        "palette": [palette_default, palette_slate],
        "features": [
            "navigation.sections",
            "navigation.expand",
            "navigation.path",
            "navigation.footer",
            "navigation.instant",
            "navigation.tracking",
            "search.suggest",
            "search.highlight",
            "search.share",
            "content.code.copy",
            "content.code.annotate",
            "toc.follow",
        ],
    }
    if book.theme.font.text or book.theme.font.code:
        theme["font"] = {
            "text": book.theme.font.text or "Roboto",
            "code": book.theme.font.code or "Roboto Mono",
        }
    if book.logo:
        theme["logo"] = str(book.logo)
    if book.favicon:
        theme["favicon"] = str(book.favicon)
    return theme


def _markdown_extensions() -> list:
    return [
        "abbr",
        "admonition",
        "attr_list",
        "footnotes",
        "md_in_html",
        "tables",
        {"toc": {"permalink": True}},
        {"pymdownx.arithmatex": {"generic": True}},
        "pymdownx.betterem",
        "pymdownx.blocks.admonition",
        "pymdownx.blocks.caption",
        "pymdownx.blocks.details",
        "pymdownx.details",
        {
            "pymdownx.highlight": {
                "anchor_linenums": True,
                "line_spans": "__span",
                "pygments_lang_class": True,
            }
        },
        "pymdownx.inlinehilite",
        "pymdownx.snippets",
        "pymdownx.superfences",
        {"pymdownx.tabbed": {"alternate_style": True}},
        {"pymdownx.tasklist": {"custom_checkbox": True}},
        "def_list",
    ]


def _nav_from_toc(toc: list) -> list:
    """Translate a ``book.yml`` TOC into an mkdocs ``nav:`` list."""
    return [_nav_entry(e) for e in toc if _nav_entry(e) is not None]


def _nav_entry(entry) -> dict | str | None:
    if isinstance(entry, FileEntry):
        if entry.hidden:
            return None
        url_path = _doc_path_for(entry.file)
        if entry.title:
            return {entry.title: url_path}
        return url_path
    if isinstance(entry, UrlEntry):
        return {entry.title: entry.url}
    if isinstance(entry, SectionEntry):
        children = [c for c in (_nav_entry(c) for c in entry.children) if c is not None]
        return {entry.section: children}
    return None


def _doc_path_for(file: Path) -> str:
    """Return the relative path within ``docs_dir`` for a TOC entry.

    - ``content/intro.md`` → ``intro.md``
    - ``content/GLM.py`` → ``GLM.md`` (marimo notebooks render to markdown)
    - ``docs/glossary.md`` → ``docs/glossary.md``
    """
    p = Path(file)
    parts = p.parts
    if parts and parts[0] == "content":
        p = Path(*parts[1:])
    if p.suffix == ".py":
        p = p.with_suffix(".md")
    return p.as_posix()


def _edit_uri_from_repo(repo_url: str) -> str:
    """Derive an ``edit_uri`` from a GitHub repo URL.

    For github.com repos mkdocs expects a path relative to the repo root,
    including the branch. We default to ``edit/main/content/`` so the
    "Edit this page" button opens the *source* marimo ``.py`` or Markdown
    file, not the generated page under ``docs/``.
    """
    if "github.com" in repo_url:
        return "edit/main/content/"
    return "edit/main/"
