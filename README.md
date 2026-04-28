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

- **Anywidgets that render statically** — interactive Canvas/Three.js/Plotly widgets without a marimo kernel
- **Static reactivity for discrete sliders** (`mo.ui.slider` with explicit steps) — pre-rendered lookup tables, no kernel
- **WASM render mode per chapter** — opt into Pyodide-driven full reactivity for chapters that need it
- **Material for MkDocs theming** — full-text search, dark mode, code-copy, breadcrumbs, responsive layout
- **Launch buttons per chapter** — molab / GitHub / download `.py`
- **Incremental build cache** — content-hashed; only changed chapters re-render
- **GitHub Pages deploy workflow** scaffolded by `marimo-book new`

## Status

**Alpha (0.1.x).** Used in production by at least one real course
([dartbrains.org](https://dartbrains.org)). The `book.yml` schema is
stable for v0.1; pin a minor version (`marimo-book>=0.1.5,<0.2`) until
1.0. Major changes always go through a new minor version.

## Install

```bash
pip install marimo-book
```

Requires Python 3.11+. Optional extras for opt-in features:

```bash
pip install 'marimo-book[social]'      # OpenGraph card generation (libcairo)
pip install 'marimo-book[linkcheck]'   # external-link verification (htmlproofer)
pip install 'marimo-book[pdf]'         # single-PDF export (WeasyPrint)
```

`mkdocs-autorefs` (cross-page heading references) ships in the base
install — flip `cross_references: true` in `book.yml` to enable.

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
(`.github/workflows/deploy.yml`) to the default branch on a repo with
Pages enabled.

## How it works

Two-stage build, by design:

```
content/*.md + *.py + book.yml
  → marimo-book preprocessor
  → _site_src/docs/*.md  +  _site_src/mkdocs.yml
  → mkdocs build (Material theme)
  → _site/
```

The preprocessor is **not** a mkdocs plugin — it emits plain Markdown +
inline HTML. This keeps the shell swappable: Material today,
[zensical](https://zensical.org) (Material's Rust successor) tomorrow,
or a hand-rolled Jinja shell as a last-resort fallback.

For each marimo `.py` it runs `marimo export ipynb --include-outputs`
and translates the cells into Markdown + inline HTML — embedding
Plotly figures, anywidget mounts, and matplotlib renders directly. For
WASM-mode chapters, it routes through marimo's `MarimoIslandGenerator`
and ships marimo's runtime + Pyodide bundle.

## `book.yml` minimal example

```yaml
title: My Book
description: A static site from marimo notebooks + Markdown.
authors:
  - name: Your Name
repo: https://github.com/you/yourbook

theme:
  palette:
    primary: "#1976D2"

launch_buttons:
  molab: true
  github: true
  download: true

# Static reactivity for discrete mo.ui widgets
precompute:
  enabled: true

toc:
  - file: content/intro.md
  - section: Chapters
    children:
      - file: content/chapter1.py
      - file: content/chapter2.py
        mode: wasm           # this one runs in Pyodide for full reactivity
```

See [`marimo-book new`](https://marimobook.org/quickstart/) for the
full starter template, and the [book.yml
reference](https://marimobook.org/book_yml/) for every field.

## Notebook dependencies

`book.yml` picks one of two modes:

- **`env` (default)**: re-use the active venv. Pin notebook deps in your
  book root's `pyproject.toml`. Fast.
- **`sandbox`**: pass `--sandbox` to `marimo export`. Each notebook
  declares its own deps via PEP 723 inline metadata; marimo provisions
  per-notebook envs via `uv`. Slower on first run; portable.

Override per invocation with `--sandbox` / `--no-sandbox` on `build` or
`serve`.

## Build cache

A content-addressed cache at `{book_root}/.marimo_book_cache/` skips
re-rendering chapters whose source + book.yml-relevant fields haven't
changed. Typical incremental rebuilds drop from 100+ s to ~3 s on
real-world books. Reset with `marimo-book clean` or override per
invocation with `marimo-book build --rebuild`. CI runners get warm
cache reuse via [`actions/cache@v4`](https://marimobook.org/building/#tuning-caps-for-heavy-notebooks).

## Broken-link checking

`marimo-book build --strict` fails on broken **in-tree** links and
anchors (use this on CI). For external URL and image `src` validation,
opt into htmlproofer:

```yaml
# book.yml
check_external_links: true
```

```bash
pip install 'marimo-book[linkcheck]'
marimo-book build --strict
```

External link checking hits the live web (~1–3 s per link), so we
recommend gating it behind a release-cutting workflow rather than
running on every PR.

## License

[MIT](LICENSE)
