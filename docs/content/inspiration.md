# Inspiration & credits

`marimo-book` stands on the shoulders of excellent prior work. This
page documents the projects that inspired specific design choices, the
libraries we build on, and the communities whose patterns we borrowed.

## Direct inspiration

### [Jupyter Book](https://jupyterbook.org) (and Jupyter Book 2)

The entire category of "a static-site book generator for computational
notebooks" was established by Jupyter Book. When we started this
project we asked: "what if Jupyter Book existed for marimo `.py`
notebooks?" Nearly every `book.yml` field has a corresponding
`_config.yml` / `_toc.yml` concept in Jupyter Book — TOC nesting,
launch buttons, theme palette, the "notebook + Markdown" mix, author
metadata, admonitions, cross-refs. If you're shipping `.ipynb` or MyST
Markdown, **use Jupyter Book 2** — it's more mature and its team knows
what they're doing.

`marimo-book` exists because marimo's reactive `.py` notebook format
isn't natively supported by any existing static-site generator.
Jupyter Book's `.ipynb` parser, MyST Markdown support, and long feature
matrix gave us a target to emulate.

### [nbdev](https://nbdev.fast.ai)

nbdev's two-stage "preprocess the notebook, then hand off to a
conventional SSG" architecture directly influenced `marimo-book`'s
design. nbdev preprocesses `.ipynb` and hands to Quarto; `marimo-book`
preprocesses `.py` and hands to Material for MkDocs. The separation
keeps the tool small and the rendering engine swappable. (nbdev's lead
maintainer Jeremy Howard also proved that dense technical books can be
pleasant to author when the tooling gets out of the way.)

### [Observable Framework](https://observablehq.com/framework)

Mike Bostock's file-routed Markdown SSG that executes data loaders in
any language at build time. The idea of "the preprocessor runs
arbitrary per-notebook code during the build and stamps the output
into the static site" isn't new — Observable did it years ago with
polish we aspire to.

## Libraries we build on

- **[marimo](https://marimo.io)** — Obviously. The whole project exists
  because marimo deserves a real static-site story. Their
  `marimo export ipynb --include-outputs` is the backbone of our
  preprocessor.
- **[Material for MkDocs](https://squidfunk.github.io/mkdocs-material/)**
  — The visual polish of `marimo-book` is Material's polish. We
  deliberately don't customize much; Martin Donath has better taste
  than we do.
- **[MkDocs](https://www.mkdocs.org)** — The shell that Material for
  MkDocs sits on. Stable, predictable, well-documented.
- **[pymdown-extensions](https://facelessuser.github.io/pymdown-extensions/)**
  — Admonitions, details, highlight, tabs, arithmatex for math. The
  CommonMark fill-in that actually makes Markdown useful for technical
  writing.
- **[anywidget](https://anywidget.dev)** — Trevor Manz's widget model
  for interactive notebooks. Our static shim is a minimal
  re-implementation of anywidget's Python ↔ JS model interface.
- **[pydantic](https://docs.pydantic.dev)** — `book.yml` schema
  validation with field-aware error messages out of the box.
- **[Typer](https://typer.tiangolo.com)** — Type-hint-driven CLI. Built
  on Click, but with the ergonomics of a library written in 2025.
- **[watchdog](https://pythonhosted.org/watchdog/)** — The file-system
  event watcher powering `marimo-book serve`'s live reload.

## Future influences

- **[zensical](https://zensical.org)** — Martin Donath's Rust-based
  successor to Material for MkDocs. `marimo-book` is architected to
  port onto zensical as soon as its extensibility story stabilises. See
  the [roadmap](roadmap.md) for details.
- **[Quarto](https://quarto.org)** — What we'd be using if we were
  authoring in `.qmd`. Quarto's book machinery is mature and its
  approach to pre-executed documents is conceptually similar to ours.

## What we learned from looking

Some projects we studied carefully but did *not* adopt directly:

- **[mkdocs-jupyter](https://github.com/danielfrg/mkdocs-jupyter)** —
  The reference for "ingest non-Markdown files as pages via mkdocs
  plugin hooks." We deliberately stayed out of the mkdocs plugin API
  and emit plain Markdown instead, so the same preprocessor output
  feeds mkdocs today and zensical tomorrow.
- **[mkdocs-marimo](https://github.com/marimo-team/mkdocs-marimo)** —
  The marimo team's official plugin. It embeds marimo cells as
  WASM-powered islands inside Markdown pages. Great for "a few live
  cells in a doc site"; less suited to our "a book of pre-executed
  notebooks" use case, which is why we built a different thing rather
  than building on top.
- **[marimushka](https://pypi.org/project/marimushka/)** — A
  third-party "portfolio of marimo notebook HTML files" generator. The
  closest thing to what we do in spirit, but portfolio-shaped rather
  than book-shaped.

## License

MIT. Reuse anything. If you port part of this to another project, a
link back is appreciated but not required.
