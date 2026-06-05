"""Auto-generated Python API reference (shell-neutral).

Loads each configured package with Griffe, stages one ``::: pkg.module``
directive page per public module into the docs tree, and returns a nested
nav subtree. The generated pages are rendered by the ``mkdocstrings`` plugin
that :mod:`marimo_book.shell` wires into ``mkdocs.yml``.

This module is shell-agnostic: it only emits Markdown + a nav structure.
Only the plugin block in :mod:`marimo_book.shell` is mkdocs-specific.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path
from typing import TYPE_CHECKING

from .config import ApiDocs

if TYPE_CHECKING:  # pragma: no cover
    from griffe import Module


def resolve_search_paths(cfg: ApiDocs, book_root: Path) -> list[Path]:
    """Resolve ``cfg.paths`` to absolute dirs relative to the book root."""
    return [(book_root / p).resolve() for p in cfg.paths]


def stage_api_docs(cfg: ApiDocs, *, search_paths: list[Path], docs_dir: Path) -> list[dict | str]:
    """Stage API pages for each package; return the nav subtree.

    The returned value is ``[{cfg.title: [<package nav>, ...]}]`` — a single
    titled section the caller splices into the book nav with ``nav.extend``.
    """
    try:
        import griffe
    except ImportError as exc:  # pragma: no cover - exercised via integration
        raise RuntimeError(
            "api_docs.enabled requires the 'api' extra. "
            "Install it with: pip install 'marimo-book[api]'"
        ) from exc

    sp = [str(p) for p in search_paths]
    section: list[dict | str] = []
    # Each root in ``cfg.packages`` is always documented; ``cfg.exclude``
    # (and the underscore rule) only prune descendant modules, never a root.
    for name in cfg.packages:
        try:
            module = griffe.load(name, search_paths=sp)
        except Exception as exc:  # noqa: BLE001 - re-raised with context
            raise RuntimeError(
                f"api_docs: could not load package '{name}'. "
                f"Searched paths: {sp or '(import path only)'}. "
                f"{exc.__class__.__name__}: {exc}"
            ) from exc
        section.append(
            _build_module(
                module,
                cfg,
                docs_dir=docs_dir,
                rel_prefix=f"{cfg.dir}/{name.replace('.', '/')}",
                label=name,
            )
        )
    return [{cfg.title: section}]


def _public_children(module: Module, cfg: ApiDocs) -> list[Module]:
    """Submodules that get their own page: non-underscore, not excluded."""
    out: list[Module] = []
    for child_name, child in sorted(module.modules.items()):
        if child_name.startswith("_"):
            continue
        if any(fnmatch.fnmatch(child.path, pat) for pat in cfg.exclude):
            continue
        out.append(child)
    return out


def _build_module(
    module: Module, cfg: ApiDocs, *, docs_dir: Path, rel_prefix: str, label: str | None = None
) -> dict:
    """Stage a page for ``module`` and return its nav entry.

    A module with public submodules becomes a package node: an ``index.md``
    plus one child entry each. A leaf module becomes a single ``<name>.md``.

    ``label`` overrides the nav key (used for dotted top-level package names so
    the full dotted name labels the section); it defaults to ``module.name`` so
    nested children keep their short-name keys.
    """
    key = label or module.name
    children = _public_children(module, cfg)
    if children:
        page_rel = f"{rel_prefix}/index.md"
        _write_page(docs_dir / page_rel, module.name, module.path)
        child_nav = [
            _build_module(c, cfg, docs_dir=docs_dir, rel_prefix=f"{rel_prefix}/{c.name}")
            for c in children
        ]
        return {key: [page_rel, *child_nav]}
    page_rel = f"{rel_prefix}.md"
    _write_page(docs_dir / page_rel, module.name, module.path)
    return {key: page_rel}


def _write_page(path: Path, title: str, dotted: str) -> None:
    """Write a minimal ``::: dotted`` directive page."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"# {title}\n\n::: {dotted}\n", encoding="utf-8")
