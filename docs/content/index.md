# marimo-book

**Build clean, searchable, static books from [marimo](https://marimo.io)
notebooks and Markdown files.**

`marimo-book` is an open-source command-line tool that turns a directory
of marimo `.py` notebooks and Markdown files — plus a small `book.yml`
config — into a polished static website with a collapsible sidebar,
full-text search, dark mode, and per-chapter launch buttons.

This site you're reading is built with `marimo-book`. Every feature it
documents is demonstrated live on the corresponding page. The
[source is on GitHub](https://github.com/ljchang/marimo-book/tree/main/docs).

## Why this exists

[marimo](https://marimo.io) is an excellent reactive Python notebook
format — but until now there's been no good way to publish a coherent
multi-chapter book from marimo notebooks. Your options were roughly:

- **Self-host individual notebook HTML files** — each one is a solid
  standalone document, but you lose cross-chapter navigation, site-wide
  search, unified theming, and the "book" feel readers expect from a
  course or tutorial series.
- **[molab](https://molab.marimo.io)** — marimo's hosted runner. Great
  for sharing a single reactive notebook with zero setup, but it's a
  per-notebook experience; you can't stitch a set of chapters into a
  browsable book with a sidebar.
- **WASM export** — `marimo export html-wasm` makes a notebook fully
  interactive in a browser via Pyodide, but pyodide is still `wasm32`,
  which caps memory at 2 GB and excludes many scientific-Python packages
  like `nibabel`, `nilearn`, and `statsmodels`. Most non-trivial data
  science books can't run in WASM.

`marimo-book` sits in the gap. It produces a **statically-rendered book**
(every cell's output is baked at build time, so readers see real results
without needing a Python kernel), with a per-chapter *"Open in molab"*
button for readers who want to run and modify the code live. Anywidgets
continue to work interactively on the static page via a small runtime
shim, and heavy chapters that can't run in WASM render fine as static
figures with a one-click escape hatch to molab.

## What it's not

- A notebook **editor** — author notebooks in marimo itself, then build
  with `marimo-book`.
- A **kernel runner** — the built site serves HTML + JS; no server-side
  execution.
- A replacement for [Jupyter Book](https://jupyterbook.org) — if you
  author in `.ipynb` or MyST Markdown, Jupyter Book 2 is the right tool.
  `marimo-book` exists because marimo's `.py` notebook format isn't
  natively supported by any existing SSG and we wanted something
  purpose-built.

## Status

Alpha (v0.1.0a1). Usable end-to-end — the tool is actively building a
real course site ([dartbrains](https://github.com/ljchang/dartbrains))
— but the `book.yml` schema may still change between minor versions
before v1.0. Pin the exact version in your project until we signal
stability.

See the [roadmap](roadmap.md) for what's coming next, including WASM
rendering, [zensical](https://zensical.org) migration, and citation
support.

## Credits

`marimo-book` exists because [Jupyter Book](https://jupyterbook.org)
proved what a beautiful notebook book can look like. The preprocessor +
swappable-shell architecture is inspired by
[nbdev](https://nbdev.fast.ai) and [Observable
Framework](https://observablehq.com/framework). The visual polish comes
for free from [Material for
MkDocs](https://squidfunk.github.io/mkdocs-material/) and, eventually,
its Rust-based successor [zensical](https://zensical.org). See
[Inspiration & credits](inspiration.md) for the full list.
