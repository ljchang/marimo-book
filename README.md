# marimo-book

Build clean, searchable static books from [marimo](https://marimo.io) notebooks and Markdown files.

`marimo-book` is a Jupyter-Book-style static site generator specifically for marimo `.py` notebooks. It produces polished multi-page sites with:

- **Collapsible sidebar** and chapter-aware navigation
- **Fast full-text search** across prose and cell outputs
- **Admonitions, math, figures, citations, cross-references**
- **Launch buttons** for opening notebooks in molab, downloading `.py` source, or viewing on GitHub
- **Clean minimal theme** (Material for MkDocs under the hood)

## Status

**Alpha.** v0.1 is in active development; dartbrains is the reference consumer. Do not depend on this in production yet.

## Quickstart (preview)

```bash
pip install marimo-book
marimo-book new mybook
cd mybook
marimo-book serve
```

## Architecture

Two-stage build:

1. **Preprocessor** reads a `book.yml` config and a mixed tree of `.md` + marimo `.py` files, emits a canonical Markdown tree.
2. **Shell** (Material for MkDocs) turns that tree into a static site.

The preprocessor is not an mkdocs plugin — it emits plain Markdown + inline HTML, so the same output works today with Material for MkDocs and later with [zensical](https://zensical.org) (which is drop-in compatible with `mkdocs.yml`).

## License

MIT
