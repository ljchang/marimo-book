# `book.yml` reference

The single source of truth for your book's configuration. The
preprocessor translates this into a generated `mkdocs.yml`; users rarely
need to touch `mkdocs.yml` directly.

Every field is optional except `title` and `toc`.

## Complete example

```yaml
title: My Book
description: A static site from marimo notebooks + Markdown.
authors:
  - name: Your Name
    orcid: 0000-0000-0000-0000
    affiliation: Somewhere
    email: you@example.org
copyright: "2026"
license: MIT
repo: https://github.com/you/your-book
branch: main
doi: 10.5281/zenodo.xxxxx

# Branding
logo: images/logo.png
favicon: images/favicon.ico
theme:
  palette:
    primary: "#1976D2"
    accent:  "#FF9800"
  font:
    text: Source Sans Pro
    code: JetBrains Mono

# Per-chapter buttons
launch_buttons:
  molab: true
  github: true
  download: true
  # wasm: true    # v0.2

# Notebook dependencies
dependencies:
  mode: env      # env | sandbox

# Per-widget-class default state (anywidgets)
widget_defaults:
  CompassWidget:
    b0: 3.0

# Analytics
analytics:
  provider: plausible   # plausible | google | none
  property: yoursite.org

# External-link check (opt-in, requires marimo-book[linkcheck])
check_external_links: false

# Cross-page heading references via mkdocs-autorefs (bundled with
# marimo-book — no extra install needed; just flip this flag).
cross_references: false

# Auto-include CHANGELOG.md from the book root as a "Changelog" page
# in the nav. No-op if no CHANGELOG.md exists at the book root.
include_changelog: false

# Single-PDF export of the entire book (opt-in,
# requires marimo-book[pdf]). Adds a "Download PDF" link to the footer.
pdf_export: false

# Render defaults (applied per-page unless overridden)
defaults:
  mode: static           # v0.2: wasm | hybrid
  hide_author_line: true
  show_source_link: true
  hide_first_code_cell: true
  suppress_warnings: false   # set true to hide library warnings in cell output

# Table of contents (nested; sections, files, external URLs)
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

shell: mkdocs   # v0.3+: zensical, jinja
```

## Minimal valid config

```yaml
title: My Book
toc:
  - file: content/intro.md
```

That's enough to build. Every other field uses a sensible default.

## Field reference

### Metadata

| Field | Type | Default | Notes |
|---|---|---|---|
| `title` | string | **required** | Shown in the header, browser tab, search index |
| `description` | string | `None` | Used as `<meta>` description and search preview |
| `authors[]` | list of `Author` | `[]` | See *Authors* below |
| `copyright` | string | `None` | Footer copyright. HTML allowed — useful for funding lines + linked author names |
| `license` | string | `None` | SPDX identifier (`MIT`, `CC-BY-SA-4.0`) |
| `repo` | URL | `None` | Enables "Edit on GitHub" links + launch buttons |
| `branch` | string | `main` | Branch that `repo` links target |
| `url` | URL | `None` | Canonical site URL. Used for absolute links in OpenGraph cards and the search index |
| `doi` | string | `None` | Renders as a badge on the landing page |

Each author supports `name` (required), `orcid`, `affiliation`, and
`email`. ORCID renders as a clickable icon next to the name.

### Branding

| Field | Type | Default | Notes |
|---|---|---|---|
| `logo` | path | `None` | Relative to book root; copied into `images/` |
| `favicon` | path | `None` | Relative to book root |
| `logo_placement` | `header` \| `sidebar` | `header` | `sidebar` puts a large logo above the left nav (Jupyter-Book chrome) |
| `theme.palette.primary` | hex color | Material default | Top bar + links. Applied to *both* schemes (light + dark) |
| `theme.palette.accent` | hex color | Material default | Highlights + active states |
| `theme.font.text` | Google Font name | `Roboto` | Body font |
| `theme.font.code` | Google Font name | `Roboto Mono` | Code font |

### Launch buttons

Each flag is a boolean. All apply per-`.py` entry; `github` is the only
one that also applies to `.md` pages.

- `molab` — "Open in molab" button. Requires `repo` to be set.
- `github` — "View on GitHub" button. Requires `repo`.
- `download` — "Download .py" button (raw `.py` source).
- `colab` / `binder` — reserved flags, no-op in v0.1.
- `wasm` — reserved for v0.2.

| Field | Type | Default | Notes |
|---|---|---|---|
| `placement` | `header` \| `page` | `header` | `header` mounts icon-only buttons in Material's top bar; `page` keeps the legacy text-button row above each chapter title |

### Dependencies

Controls how notebook imports get resolved at build time. See
[Authoring → Dependencies](dependencies.md) for the full walkthrough.

```yaml
dependencies:
  mode: env       # default — use the active venv
  # mode: sandbox — PEP 723 per-notebook isolation via uv
```

### Widget defaults

A map from anywidget Python class name to the initial state the widget's
JS needs on first paint. Literal kwargs extracted from each cell
override these defaults. See [Authoring → Anywidgets](widgets.md).

### Analytics

Opt-in Plausible or Google Analytics. Injected via Material for MkDocs'
`extra.analytics` block; Material auto-injects the gtag.js / Plausible
script on every page.

| Field | Type | Default | Notes |
|---|---|---|---|
| `analytics.provider` | `plausible` \| `google` \| `none` | `none` | Off by default. Both providers live in the Material analytics integration |
| `analytics.property` | string | `None` | GA4 Measurement ID (`G-XXXXXXXXXX`) for Google, or domain (`yoursite.org`) for Plausible. Universal Analytics IDs (`UA-...`) are not supported — Google retired UA on 2023-07-01 |

```yaml
analytics:
  provider: google
  property: G-XXXXXXXXXX
```

### Static reactivity (`precompute`)

Re-renders the notebook once per discrete-widget value at build time
and ships a JSON lookup table the JS shim swaps on slider input. Off
by default; opt in per book.

| Field | Type | Default | Notes |
|---|---|---|---|
| `precompute.enabled` | bool | `false` | Flip on to scan every `.py` page for `mo.ui.slider(steps=...)` / `mo.ui.dropdown` / `mo.ui.switch` / `mo.ui.radio` candidates |
| `precompute.max_values_per_widget` | int | `50` | Skip a widget whose value set exceeds this. Cheap cap, checked before any execution |
| `precompute.max_combinations_per_page` | int | `200` | Across all widgets on a page (cartesian product when multiple widgets share a downstream cell). Cheap cap |
| `precompute.max_seconds_per_page` | int | `60` | Wall-clock budget per page. The orchestrator extrapolates from the first export and aborts if projected runtime exceeds. Bump to 600+ for heavy chapters (whole-brain decomposition, fMRI processing, etc.) |
| `precompute.max_bytes_per_page` | int | `10485760` (10 MB) | Inline-table budget. Bump to 50 MB for chapters whose per-render output is large (e.g. inline brain HTML viewers) |
| `precompute.exclude_pages[]` | list of paths | `[]` | Pages listed here render every widget as static even when the global flag is on |

See [Building → Static reactivity](building.md#static-reactivity-precompute)
for the full pipeline + tuning guide.

### Bibliography

| Field | Type | Default | Notes |
|---|---|---|---|
| `bibliography` | list of paths | `[]` | BibTeX files to load. Inline list shorthand also accepted (`bibliography: [refs.bib, more.bib]`) |
| `cite_style` | `apa` \| `numbered` | `apa` | Citation rendering format |

### Defaults

Page-level rendering defaults.

| Field | Type | Default | Notes |
|---|---|---|---|
| `mode` | `static` \| `wasm` | `static` | Render mode for `.py` notebooks |
| `hide_author_line` | bool | `true` | Hide the author byline rendered into each chapter |
| `show_source_link` | bool | `true` | Show the source-link icon next to the title |
| `hide_first_code_cell` | bool | `true` | Drop the conventional `import marimo as mo` setup cell |
| `suppress_warnings` | bool | `false` | Run notebook export with `PYTHONWARNINGS=ignore` so library warnings don't surface as visible stderr blocks in the page |

`suppress_warnings: true` is useful for tutorial books that import
scientific libraries — numpy, pandas, scikit-learn, etc. routinely
emit deprecation and conversion warnings that distract from the
lesson. The flag suppresses warnings at the kernel level (not in
post-processing), so they're never captured as cell stderr.
Genuine errors still surface; only `warnings.warn(...)` output is
silenced.

### TOC entries

Three shapes, inferred from which key is present:

- `file: path` — a local `.md` or marimo `.py`, rendered as a page.
  Optional `title:` overrides the first `#` heading in the file. Optional
  `mode: wasm` opts that page into [WASM render mode][wasm].
- `url: URL` (+ `title:`) — external link in the sidebar.
- `section: name` + `children: [...]` — a nested group. Recursive. An
  empty section (`children:` blank or omitted) is silently dropped from
  the nav, so you can stub out future groups without breaking the build.

**The first `file:` entry becomes the home page.** Whatever it is —
`content/intro.md`, `content/welcome.py`, anything — gets staged as
`index.md` in the docs tree, so mkdocs serves it at `/`. This means the
header logo's "back to home" link works without any extra configuration,
and you don't need to know about the mkdocs `index.md` convention.

[wasm]: building.md#wasm-render-mode

### Shell

The underlying static-site generator. In v0.1 only `mkdocs` is
supported. v0.3 adds `zensical`; `jinja` is a planned fallback.
