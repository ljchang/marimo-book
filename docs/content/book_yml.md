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

# Render defaults (applied per-page unless overridden)
defaults:
  mode: static           # v0.2: wasm | hybrid
  hide_author_line: true
  show_source_link: true
  hide_first_code_cell: true

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
| `copyright` | string | `None` | Footer copyright |
| `license` | string | `None` | SPDX identifier (`MIT`, `CC-BY-SA-4.0`) |
| `repo` | URL | `None` | Enables "Edit on GitHub" links + launch buttons |
| `branch` | string | `main` | Branch that `repo` links target |
| `doi` | string | `None` | Renders as a badge on the landing page |

Each author supports `name` (required), `orcid`, `affiliation`, and
`email`. ORCID renders as a clickable icon next to the name.

### Branding

| Field | Type | Default | Notes |
|---|---|---|---|
| `logo` | path | `None` | Relative to book root; copied into `images/` |
| `favicon` | path | `None` | Relative to book root |
| `theme.palette.primary` | hex color | Material default | Top bar + links |
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
`extra.analytics` block.

### Defaults

Page-level rendering defaults. The most useful one today:
`hide_first_code_cell: true` hides the first code cell of every marimo
notebook (almost always `import marimo as mo` setup) so it doesn't
clutter the rendered page. Set to `false` if you want the setup visible.

### TOC entries

Three shapes, inferred from which key is present:

- `file: path` — a local `.md` or marimo `.py`, rendered as a page.
  Optional `title:` overrides the first `#` heading in the file.
- `url: URL` (+ `title:`) — external link in the sidebar.
- `section: name` + `children: [...]` — a nested group. Recursive.

### Shell

The underlying static-site generator. In v0.1 only `mkdocs` is
supported. v0.3 adds `zensical`; `jinja` is a planned fallback.
