# marimo-book

[![PyPI version](https://img.shields.io/pypi/v/marimo-book.svg)](https://pypi.org/project/marimo-book/)
[![Python versions](https://img.shields.io/pypi/pyversions/marimo-book.svg)](https://pypi.org/project/marimo-book/)
[![CI](https://github.com/ljchang/marimo-book/actions/workflows/ci.yml/badge.svg)](https://github.com/ljchang/marimo-book/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Docs](https://img.shields.io/badge/docs-latest-blue)](https://marimobook.org/)

Build clean, searchable static books from [marimo](https://marimo.io)
notebooks and Markdown files.

`marimo-book` is a Jupyter-Book-style static site generator built
specifically for marimo `.py` notebooks. It produces polished multi-page
sites with:

- **Collapsible sidebar** and chapter-aware navigation
- **Fast full-text search** across prose *and* baked cell outputs
- **Admonitions, math, figures, tables** with Material for MkDocs defaults
- **Anywidgets that render statically** (no marimo kernel required)
- **Launch buttons** per-chapter for molab / GitHub / download `.py`
- **Dark-mode toggle** that persists across navigation
- **GitHub Pages deploy workflow** scaffolded in for you

## Status

**Alpha** (v0.1.0a1, April 2026). `marimo-book` is usable end-to-end and is
actively building a real course site ([dartbrains](https://github.com/ljchang/dartbrains)),
but the `book.yml` schema may still change before v1.0. Pin the exact version
in your project until we signal stability.

## Install

```bash
pip install marimo-book
```

Requires Python 3.11+.

## Quickstart

```bash
# Scaffold a new book
marimo-book new mybook
cd mybook

# Live-reload dev server (http://127.0.0.1:8000/)
marimo-book serve
#
# Note on macOS: mkdocs's browser auto-reload is flaky on some
# macOS setups. If the browser doesn't refresh automatically after a
# save, hard-refresh (Cmd-R). The preprocessor + rebuild are
# reliable; only the browser push is affected.

# One-shot static build (emits ./_site/)
marimo-book build

# Validate book.yml + content without building
marimo-book check

# Remove build artifacts
marimo-book clean
```

Deploy to GitHub Pages by pushing the scaffolded workflow
(`.github/workflows/deploy.yml`) to `main` on a repo with Pages enabled.

## How it works

Two-stage build, by design:

```
content/*.md + *.py + book.yml
  → marimo-book preprocessor
  → _site_src/docs/*.md  +  _site_src/mkdocs.yml
  → mkdocs build (Material theme)
  → _site/
```

1. The preprocessor reads `book.yml` and walks the TOC. For each `.md` it
   applies small content transforms (`../images/` path fixups, `.ipynb` →
   `.md` cross-ref rewriting). For each marimo `.py` it runs
   `marimo export ipynb --include-outputs` and converts the cells into
   Markdown + inline HTML, translating marimo custom elements
   (`<marimo-callout-output>`, `<marimo-anywidget>`) into their static
   analogs.
2. Material for MkDocs (or later, zensical — which reuses `mkdocs.yml`
   verbatim) builds the final HTML.

The preprocessor is **not** a mkdocs plugin — it emits plain Markdown +
inline HTML. This keeps the shell swappable: Material today, zensical
tomorrow, or a hand-rolled Jinja shell as a last-resort fallback.

## `book.yml`

```yaml
title: My Book
description: A static site from marimo notebooks + Markdown.
authors:
  - name: Your Name
    orcid: 0000-0000-0000-0000       # optional
repo: https://github.com/you/yourbook
branch: main

theme:
  palette:
    primary: "#1976D2"
    accent:  "#FF9800"

launch_buttons:
  molab: true          # "Open in molab" button on every .py page
  github: true         # "View on GitHub"
  download: true       # "Download .py source"

# Per-widget default state for anywidgets whose JS needs initial model
# values to render on first paint. Literal kwargs from the cell override
# these; unset keys fall through to the widget's own JS defaults.
widget_defaults:
  CompassWidget:
    b0: 3.0

toc:
  - file: content/intro.md
  - section: Part I
    children:
      - file: content/chapter1.py
      - file: content/chapter2.py
  - section: Part II
    children:
      - file: content/chapter3.py
      - url: https://example.org/external-reading
        title: External Reading
```

See `marimo-book new` for a full starter template with comments on every
field.

## What's supported in v0.1

**Material for MkDocs handles natively (free):**

- Full-text search, dark mode, keyboard shortcuts, code-copy buttons,
  collapsible sidebar, breadcrumbs, next/previous navigation,
  admonitions (`!!! note` / `!!! tip` / `!!! warning` / etc.), math,
  responsive theme, edit-this-page link, analytics, top-of-page banner

**Preprocessor adds:**

- `book.yml` → `mkdocs.yml` generation (TOC, theme, palette, fonts,
  extensions, plugins all derived)
- `.py` → rendered Markdown + inlined anywidget / callout / image outputs
- Static rehydration of anywidgets via a small JS shim
  (`marimo_book.js`, loaded via `extra_javascript`)
- Launch-button row per chapter (molab / GitHub / download)
- `[text](Foo.ipynb)` → `[text](Foo.md)` cross-ref rewrite when `Foo.md`
  exists in the staged tree
- `../images/` → `images/` relative-path fixup when `content/` is flattened
- First-code-cell hiding (the setup-imports convention) — opt out via
  `defaults.hide_first_code_cell: false`

## Notebook dependencies

Notebooks need their imports satisfied at build time (marimo re-executes
every cell to capture outputs). `marimo-book` supports two modes; pick
in `book.yml`:

```yaml
dependencies:
  mode: env       # default — reuse the active venv
  # mode: sandbox # per-notebook PEP 723 isolation via uv
```

**`env` mode** (default). Whatever Python env runs `marimo-book` provides
the deps. The typical consumer has a `pyproject.toml` at the book root
listing notebook dependencies (`numpy`, `pandas`, your domain package,
etc.), installs with `pip install -e .` or `uv pip install -e .`, and
runs `marimo-book` from that env. Fast, straightforward, good when all
notebooks share the same stack.

**`sandbox` mode.** Passes `--sandbox` to `marimo export`. Each notebook
must declare its own deps via PEP 723 inline script metadata:

```python
# /// script
# dependencies = [
#     "marimo>=0.23",
#     "numpy>=2.0",
#     "pandas>=2.0",
# ]
# ///

import marimo
# ...
```

At build time, marimo uses `uv run --isolated` to provision a fresh env
per notebook. ~5–10 s on first run, cached after. Notebooks become
portable — copy a `.py` into any repo with `uv` installed and it just
works. The book root doesn't need a `pyproject.toml`.

**Override per invocation:**

```bash
marimo-book build --sandbox    # force sandbox regardless of book.yml
marimo-book build --no-sandbox # force env mode
marimo-book serve --sandbox    # slower iteration, but reproducible
```

Use `env` for local dev loops and `sandbox` on CI where reproducibility
matters more than rebuild speed.

## Broken-link checking

`mkdocs build --strict` (use `marimo-book build --strict`) already fails on
broken **in-tree** links and anchors. For external URLs and image `src`
attributes, opt into the `htmlproofer` plugin:

```yaml
# book.yml
check_external_links: true
```

```bash
pip install 'marimo-book[linkcheck]'
marimo-book build --strict
```

External link checking hits the live web, so it's slow (~1–3 s per link).
Keep it off on CI unless you're cutting a release.

**Not in v0.1 (planned):**

- WASM / hybrid render modes — static only in v0.1; architecture already
  supports the branch
- Dependency-graph-aware incremental build cache
- BibTeX citations with hover-cards (no book needs them yet)
- PDF / EPUB export — opt-in via `mkdocs-with-pdf` if needed

## License

[MIT](LICENSE)
