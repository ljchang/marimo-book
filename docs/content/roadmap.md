# Roadmap

`marimo-book` is alpha (v0.1.0a1) and evolving. This page is the
public-facing summary of what's shipped, what's in flight, and what's
on the medium-term horizon. Plans change; treat this as a direction,
not a contract.

## Where v0.1 stands

The 0.1 series is the first stable surface — all the CLI commands,
the `book.yml` schema, the preprocessor pipeline, anywidget +
Plotly + WASM rendering, static-reactivity precompute, the build
cache, and Material-shell theming all ship today. See the
[changelog](changelog.md) for the granular release-by-release
history; below is what's coming next.

## Next up (v0.2, in planning)

### Subgraph re-execution for precompute

Today's precompute (Path X) re-runs the full notebook per widget
value. Path Y would drive marimo's `App.embed()` / `_ast` API directly
to execute *only the downstream subgraph*, often 10-100× faster.
Critical for chapters with expensive setup cells (large data loads,
ICA decompositions) where wrapping in `mo.persistent_cache` only
helps so much.

### Dependency-graph-aware build cache

Marimo already computes a reactive DAG per notebook. Emit a build
manifest so `marimo-book build` re-executes *only the cells whose
upstream dependencies changed*, not the whole notebook. Today's
chapter-level cache invalidates on any source-file change; a
cell-level cache would let one-line prose edits skip re-execution
entirely.

### Citation hover-cards

BibTeX ingest + `[@key]` rendering with Material's card syntax showing
authors, title, year, DOI on hover. Modern-doc-site parity.

## Medium term (v0.3+)

### Port to zensical

[Zensical](https://zensical.org) is Material for MkDocs' Rust-based
successor, built by the same team. It's designed for drop-in
compatibility: same `mkdocs.yml`, same Python Markdown extensions,
same custom CSS/JS, with minor MiniJinja template tweaks.

`marimo-book`'s architecture is deliberately shell-agnostic — the
preprocessor emits plain Markdown + inline HTML, not mkdocs-plugin
artifacts. When zensical stabilizes, flipping to it will be one
command change in CI:

```diff
- marimo-book build   # runs `mkdocs build` under the hood
+ marimo-book build --shell zensical  # runs `zensical build`
```

Expected differentiators: 4–5× faster builds via zensical's
differential-build engine, a faster client search (Disco), and a
longer support runway than Material for MkDocs which is entering
12-month maintenance mode.

**Smoke test — 2026-04-24 (zensical 0.0.36):** a `pip install zensical`
run against the `_site_src/mkdocs.yml` that `marimo-book build` emits
*builds successfully in 0.21s* — ~5× the speed of MkDocs on this site
— and picks up our custom `extra.css`, Inter/JetBrains Mono fonts,
and `theme.palette` hex. Observations from the first build:

- The Rust core panics (`invariant: Format(Path(RootDir))`) on
  absolute `site_dir` paths. `shell.py` currently emits absolute
  paths; the port will need to emit relative or pre-resolve.
- `zensical new` generates a `zensical.toml` with a different
  schema than `mkdocs.yml` (TOML tables, no `plugins:`, Lucide icons
  instead of `material/*`). The compat-page claim of "no new config
  format to learn" is currently aspirational; a real port will still
  want to emit a zensical-native config rather than relying on the
  YAML fallback.
- Plugins we use (`social`, `htmlproofer`) are not in zensical's
  0.0.x plugin surface yet. Search is built-in (Disco).
- Nav entries lose explicit `title:` labels; zensical uses the
  page's `# H1` instead. Preserving TOC titles will need a config
  or preprocessor change.
- Our icon uses (`material/weather-sunny`) render as Lucide
  substitutes.

Net: zensical is further along than the 2026 v0.3 expectation, but
still 0.0.x. A real port remains a v0.3 item, not a near-term swap.

Timeline: tracking zensical's own trajectory, not ours. Likely
6–12 months out.

### Per-notebook dependency override

Mix `env` and `sandbox` modes within the same book by overriding at
the entry level:

```yaml
toc:
  - file: content/heavy-notebook.py
    dependencies: sandbox    # this one gets its own env
```

### First-class BibTeX + `{cite}` / `[@key]`

Full citation support: inline `[@smith2020]`, auto-generated
references page, APA + numbered styles. Uses
[`pybtex`](https://pybtex.org).

### Multi-book cross-references

Link from one `marimo-book` site to a chapter in another (similar to
Sphinx's intersphinx or Jupyter Book's `xref:`). Low priority — we
haven't met a user who needs this yet.

## Not on the roadmap

Things we've deliberately decided not to do, with reasoning:

- **PDF / EPUB / Word export.** Orthogonal to a web-first tool. Users
  who need PDF output can layer
  [`mkdocs-with-pdf`](https://github.com/orzih/mkdocs-with-pdf) on top
  of the generated `mkdocs.yml`.
- **A notebook editor.** Author in marimo itself; `marimo-book` only
  builds.
- **A kernel runner.** The static site serves HTML + JS; no server-side
  execution. Reactivity comes from anywidgets (client-side) or molab
  (external).
- **MyST syntax.** marimo-book uses Material for MkDocs's Markdown dialect
  (`!!! note` for admonitions, `[label](page.md)` for cross-refs). Existing
  Jupyter Book content using MyST directives like `:::{glossary}` or roles
  like `{download}` needs a one-time migration to Material syntax.

## How to influence this

`marimo-book` is open and transparent. Everything above is a hypothesis
about what users need — your use case might shift priorities.

- **File an issue** on [github.com/ljchang/marimo-book/issues](https://github.com/ljchang/marimo-book/issues)
  describing what you're trying to publish and what's blocking you.
- **Send a pull request** — the project is MIT-licensed, tests are
  green and fast, and the architecture is small enough to comprehend
  in an afternoon.
- **Build your own book** and tell us what broke. The tool is in active
  use on at least [one real course](https://dartbrains.org) but needs
  more consumers to surface the things we haven't hit yet.
