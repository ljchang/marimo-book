# Roadmap

`marimo-book` is alpha (v0.1.0a1) and evolving. This page is the
public-facing summary of what's shipped, what's in flight, and what's
on the medium-term horizon. Plans change; treat this as a direction,
not a contract.

## Shipped in v0.1 (April 2026)

- Five working CLI commands: `new`, `build`, `serve`, `check`, `clean`
- `book.yml` schema (pydantic v2) covering title, authors, branding,
  palette, launch buttons, per-widget defaults, analytics,
  dependencies mode, external-link checker flag, TOC
- Preprocessor transforms: marimo `.py` → Markdown + inlined outputs;
  callouts, anywidgets, `{download}` role, `:::{glossary}` fences,
  `.ipynb` cross-ref rewrite, `../images/` path fixup
- Anywidget runtime shim (client-side rehydration, no marimo kernel)
- Material for MkDocs shell with sensible defaults; dark mode,
  full-text search, code-copy buttons, responsive theme
- GitHub Pages deploy workflow scaffolded by `marimo-book new`
- `sandbox` dependency mode (PEP 723 per-notebook isolation via `uv`)
- MIT license; PyPI Trusted Publishing workflow

## Next up (v0.2, in planning)

### WASM / hybrid render modes

Enable per-chapter interactivity without requiring a marimo kernel.
Three modes, per-entry selection in `book.yml`:

```yaml
toc:
  - file: content/MR_Physics.py
    mode: wasm      # runs reactively in-browser via Pyodide
  - file: content/GLM.py
    mode: hybrid    # static by default, "Run interactively" button swaps in WASM
  - file: content/Preprocessing.py
    mode: static    # current behaviour
```

Pyodide remains `wasm32` (2 GB memory cap, no `nibabel`/`nilearn`
support), so WASM works best for lightweight pedagogical chapters
(physics simulations, small-data demos). Heavy fMRI chapters stay
`static` with a molab escape hatch.

### Dependency-graph-aware build cache

Marimo already computes a reactive DAG per notebook. Emit a build
manifest so `marimo-book build` re-executes *only the cells whose
upstream dependencies changed*, not the whole notebook. This is our
single biggest authoring-UX lever — today's full rebuild of a 30-page
book can take a minute; a smart cache would bring incremental edits to
under 1 s.

### Citation hover-cards

BibTeX ingest + `[@key]` rendering with Material's card syntax showing
authors, title, year, DOI on hover. Modern-doc-site parity.

### "Open in marimo WASM" launch button

Replaces Jupyter Book's Thebe integration with marimo's native WASM
bundle. Zero-install, in-page interactivity from any static chapter
that fits within Pyodide's constraints.

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
- **Perfect MyST syntax compatibility.** We support the MyST directives
  and roles that actual books use; the long tail (`{numref}`,
  `{glossary}`, `{xref}`, etc.) is case-by-case.

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
