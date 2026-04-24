# marimo-book

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
   applies small content transforms (MyST `:::{glossary}` fence stripping,
   `{download}` role rewrite, `../images/` path fixups, `.ipynb` →
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
- MyST `{download}\`label <path>\`` → `[label](path)`
- `:::{glossary}` fence stripping (definition lists pass through natively)
- `[text](Foo.ipynb)` → `[text](Foo.md)` cross-ref rewrite when `Foo.md`
  exists in the staged tree
- `../images/` → `images/` relative-path fixup when `content/` is flattened
- First-code-cell hiding (the setup-imports convention) — opt out via
  `defaults.hide_first_code_cell: false`

**Not in v0.1 (planned):**

- WASM / hybrid render modes — static only in v0.1; architecture already
  supports the branch
- Dependency-graph-aware incremental build cache
- BibTeX citations with hover-cards (no book needs them yet)
- PDF / EPUB export — opt-in via `mkdocs-with-pdf` if needed

## License

[MIT](LICENSE)
