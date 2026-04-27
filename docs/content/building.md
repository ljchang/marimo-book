# Building

Reference for `marimo-book`'s build pipeline, every CLI command, and
all opt-in features.

## How a build works

`marimo-book` is a two-stage pipeline:

```
content/*.md + *.py + book.yml
  ↓ marimo-book preprocessor   (validates config, walks TOC, renders pages)
  ↓
_site_src/
├── docs/
│   ├── intro.md            ← copied from content/
│   ├── chapter1.md         ← rendered from chapter1.py via `marimo export`
│   ├── stylesheets/extra.css
│   ├── javascripts/marimo_book.js
│   └── images/             ← assets copied verbatim
├── mkdocs.yml              ← fully derived from book.yml
└── changelog.md            ← optional, when include_changelog: true
  ↓ mkdocs build (Material theme + plugins)
  ↓
_site/                       ← final static HTML, ready to deploy
```

The preprocessor never shells out to mkdocs; it just emits the
artifacts mkdocs can consume. This keeps the shell swappable —
[zensical](https://zensical.org) (Material's Rust successor) reuses
the same `mkdocs.yml` verbatim.

## Build cache

`marimo export ipynb` re-executes every cell in a notebook from scratch
— the dominant cost for any book with non-trivial computation. To
avoid paying that cost on every rebuild, the preprocessor maintains a
content-addressed cache.

**How it works**

After each successful build, the preprocessor writes a manifest at
`{book_root}/.marimo_book_cache/manifest.json` recording, per `.py`
TOC entry: source mtime, source SHA-256, the staged output path, and
a timestamp. On the next build it consults the manifest:

| Check | If true | If false |
|---|---|---|
| `cache.version` matches current schema | continue | full miss (reset cache) |
| `marimo_book_version` matches | continue | full miss |
| Hash of relevant `book.yml` fields matches | continue | full miss |
| Per-entry: source mtime unchanged | **HIT** (skip render) | hash check |
| Per-entry: source hash unchanged | **HIT** (refresh mtime) | MISS — re-render |

`book.yml` fields that invalidate the cache: `widget_defaults`,
`defaults`, `dependencies`, `launch_buttons`, `repo`, `branch`, the
flattened `toc`. Fields that don't (palette, fonts, title, analytics)
only affect `mkdocs.yml` emission, which is always re-run.

**Markdown TOC entries are not cached** — Markdown render takes
~10 ms each, so the bookkeeping isn't worth it.

**What the cache cannot detect** (use `--rebuild` for these):

- Data files the notebook reads (`pd.read_csv("data/foo.csv")`)
- `env`-mode dependency upgrades (`pip install -U numpy`)
- `sandbox`-mode PEP 723 dep changes inside the notebook (the
  notebook's own mtime catches *some* of these, but pinned versions
  on disk that change underneath you don't)
- A `marimo` package upgrade (rare; bump the marimo-book version
  yourself or `--rebuild` if a notebook starts rendering wrong)

**Inspecting the cache**

```bash
cat .marimo_book_cache/manifest.json | jq .
```

Hand-edit at your peril; the next build will overwrite anything you
change. To reset: `marimo-book clean` (removes `_site/`, `_site_src/`,
and `.marimo_book_cache/`) or `marimo-book build --rebuild` (rebuilds
fresh + repopulates the cache in one step).

## CLI commands

### `marimo-book new <directory>`

Scaffold a fresh book.

```bash
marimo-book new mybook
cd mybook && marimo-book serve
```

**Options**

| Flag | Effect |
|---|---|
| `--force` | Write into an existing non-empty directory (may overwrite) |

The scaffold ships `book.yml`, `content/intro.md`, `content/example.py`,
a GitHub Pages workflow at `.github/workflows/deploy.yml`, a
`.gitignore`, and a starter README.

### `marimo-book build`

One-shot static build. Emits `_site/` ready to deploy.

```bash
marimo-book build                          # default: book.yml in cwd
marimo-book build -b docs/book.yml         # explicit config path
marimo-book build -o public --strict       # custom output, fail on warnings
marimo-book build --clean --sandbox        # clean rebuild + force sandbox
```

**Options**

| Flag | Default | Effect |
|---|---|---|
| `-b`, `--book PATH` | `book.yml` | Path to the book.yml config |
| `-o`, `--output PATH` | `_site` | Output directory |
| `--strict` | off | Fail on warnings (broken in-tree links, missing files, etc.) |
| `--clean` | off | Remove `_site/`, `_site_src/`, and `.marimo_book_cache/` before building (implies `--rebuild`) |
| `--rebuild` | off | Re-render every notebook regardless of cache state — use when data files or env-mode deps changed |
| `--sandbox` / `--no-sandbox` | follow `book.yml` | Override the dependency mode |

**Use `--strict` in CI.** It surfaces issues that would otherwise be
silent on a successful build.

**Use `--clean` when cutting a release.** Otherwise stale files from
removed TOC entries linger in `_site_src/` (intentional, for fast
incremental dev builds; not what you want in production).

### `marimo-book serve`

Live-reload dev server.

```bash
marimo-book serve                          # http://127.0.0.1:8000/
marimo-book serve --port 9000 --no-watch
marimo-book serve --sandbox                # slower iteration, but reproducible
```

Runs an initial build, then a watchdog observer re-runs the
preprocessor when files change under `content/` or `book.yml` is
edited. mkdocs's livereload pushes the browser refresh.

**Options**

| Flag | Default | Effect |
|---|---|---|
| `-b`, `--book PATH` | `book.yml` | Path to the book.yml config |
| `--host TEXT` | `127.0.0.1` | Dev-server bind address |
| `--port INTEGER` | `8000` | Dev-server port |
| `--no-watch` | off | Disable the source watcher (useful for debugging) |
| `--rebuild` | off | Cold-build the initial render (watcher rebuilds always honour the cache) |
| `--sandbox` / `--no-sandbox` | follow `book.yml` | Override the dependency mode |

!!! warning "macOS browser-reload flake"
    On some macOS setups, mkdocs's browser auto-reload doesn't always
    fire. The build pipeline itself is reliable; if the browser
    doesn't refresh, hard-refresh (⌘-R).

### `marimo-book check`

Validate `book.yml` and linked content without building. Fast — no
mkdocs invocation, no `marimo export`.

```bash
marimo-book check                          # any errors → exit 1
marimo-book check --strict                 # warnings → exit 1 too
```

Catches: malformed `book.yml`, TOC entries pointing at missing files,
unsupported file types. Use as a pre-commit hook for fast feedback.

### `marimo-book clean`

Remove build artifacts.

```bash
marimo-book clean                          # removes _site/, _site_src/, cache
marimo-book clean -o public                # custom output dir
```

## Optional features (opt-in via `book.yml`)

Each flag is opt-in (default off) and may require an extra:

```bash
pip install 'marimo-book[social,autorefs,linkcheck,pdf]'
```

| Flag | What it does | Extra |
|---|---|---|
| `social_cards: true` | Material's `social` plugin auto-generates per-page OpenGraph / Twitter card PNGs and injects the matching `<meta>` tags | `marimo-book[social]` (also needs system `libcairo2 libpango-1.0-0 libpangocairo-1.0-0`) |
| `cross_references: true` | `mkdocs-autorefs` resolves `[Heading text][]` to whichever page contains that heading — the MkDocs analog of MyST `{ref}` | `marimo-book[autorefs]` |
| `check_external_links: true` | `htmlproofer` HEAD-checks every `<a href>` and `<img src>` against the live web | `marimo-book[linkcheck]` |
| `include_changelog: true` | Preprocessor copies `CHANGELOG.md` from the book root (or its parent) into the staged tree and appends a "Changelog" entry to the nav | None |
| `pdf_export: true` | `mkdocs-with-pdf` renders the entire book through WeasyPrint into `_site/pdf/book.pdf` and adds a "Download PDF" link to the page footer | `marimo-book[pdf]` (also needs the cairo + pango system libs above) |

### `social_cards` — OpenGraph previews

Enable when you care about how the book looks when shared on social
media. Cards inherit your `theme.palette.primary` for the background
colour. ~5 s overhead per build for ~20 pages.

### `cross_references` — autorefs

With `cross_references: true`, you can write:

```markdown
The [Anywidgets][] page covers the JS shim in detail.
```

…and `[Anywidgets][]` resolves to whichever page has `# Anywidgets`
as a heading. Lets you reorganise nav structure without breaking
inbound links.

### `check_external_links` — htmlproofer

Slow (~1–3 s per outbound link). Keep off in CI for normal builds and
turn on only when cutting a release. Combined with
`marimo-book build --strict`, broken external links fail the build.

### `include_changelog` — auto-publish CHANGELOG.md

Single source of truth: the `CHANGELOG.md` PyPI links to also becomes
a docs page. Looks first at `book_dir/CHANGELOG.md`, falls back to
`book_dir.parent/CHANGELOG.md` so the common docs/-subdir layout works
without extra config. Silent no-op when no `CHANGELOG.md` exists.

### `pdf_export` — single-PDF download

Renders the entire book to one PDF. Adds a "Download PDF" link to the
footer of every page. Slow on large books (~30 s for ~50 pages); turn
off in `serve` and on in CI / for release builds.

```yaml
# book.yml
pdf_export: true
```

The PDF inherits cover page metadata from your `book.yml`:

- Cover title ← `title`
- Cover subtitle ← `description`
- Author ← `authors[*].name`
- Copyright ← `copyright`

Output lands at `_site/pdf/book.pdf`. Wire it into your deploy by
copying the whole `_site/` directory as usual.

!!! tip "PDF builds in CI only"
    Local dev rarely needs the PDF. Set `pdf_export: false` in your
    primary `book.yml` and override in CI:

    ```bash
    PDF_EXPORT=true marimo-book build --strict
    ```

    …and tweak `book.yml` to read the env var. Or maintain a
    `book.ci.yml` variant just for the deploy job.

## Output layout

After `marimo-book build`:

```
your-book/
├── book.yml
├── content/                ← your sources (untouched)
├── _site_src/              ← preprocessor output (intermediate)
│   ├── docs/               ← staged Markdown + assets
│   └── mkdocs.yml          ← generated from book.yml
└── _site/                  ← final HTML (deploy this)
    ├── index.html
    ├── intro/index.html
    ├── chapter1/index.html
    ├── assets/             ← Material's CSS/JS
    ├── stylesheets/extra.css
    ├── search/             ← search index
    ├── sitemap.xml
    └── pdf/book.pdf        ← only if pdf_export: true
```

`_site_src/` is intentionally preserved between builds — incremental
rebuilds in `serve` are much faster when the staged tree exists. To
force a wholly fresh build, use `marimo-book build --clean`.

## Static reactivity

`marimo-book` can give static pages a *real* feel of interactivity for
marimo's discrete UI widgets — without a Python kernel at runtime. The
preprocessor re-executes the notebook once per widget value at build
time, ships the resulting cell outputs as a JSON lookup table, and a
small JS shim swaps the affected cells when the reader interacts with
the widget.

**This is the kernel-free reactivity path for `defaults.mode: static`
(the default).** WASM-rendered pages get native reactivity via Pyodide
and this whole pipeline is a no-op for them — the static fallback
works the same way either side of that line. See
[WASM render mode](#wasm-render-mode) below.

### Opt in via `book.yml`

```yaml
precompute:
  enabled: true                     # off by default
  max_values_per_widget: 50         # graceful skip if a widget has more
  max_combinations_per_page: 200    # graceful skip on multi-widget pages
  max_seconds_per_page: 60          # wall-clock budget for one page
  max_bytes_per_page: 10485760      # 10 MB inline-table budget
  exclude_pages: []                 # ["content/heavy_chapter.py"]
```

All caps default to safe values that work for typical exploratory
notebooks. **Over-cap = render static, log a warning** — the build
doesn't fail unless `--strict` is passed.

### What's a precompute candidate?

The widget IS the annotation. Authors write normal marimo code; the
choice between discrete and continuous widgets implicitly declares
candidacy. Notebooks stay portable — zero imports from marimo-book
in the `.py` source.

| Widget call | Precompute? |
|---|---|
| `mo.ui.slider(steps=[0, 1, 5, 10])` | ✅ explicit value list |
| `mo.ui.slider(0, 10, step=1)` | ✅ explicit step |
| `mo.ui.slider(0, 10)` (no step) | ❌ continuous, render static |
| `mo.ui.dropdown(options=["a", "b"])` | ✅ |
| `mo.ui.dropdown(options={"a": 1, "b": 2})` | ✅ keys enumerated |
| `mo.ui.switch()` / `mo.ui.checkbox()` | ✅ two values |
| `mo.ui.radio(options=[...])` | ✅ |
| `mo.ui.range_slider(...)` | ❌ deferred to v2 |
| Widget created via non-literal call (`make_slider(low, high)`) | ❌ value set not statically extractable |

Continuous sliders and any widget the AST scanner can't statically
resolve fall back to the existing static render — no surprises, no
silent failures.

### What's NOT in v1

- **Multi-widget pages.** A page with two precomputable widgets falls
  back to static for both, with a warning. The cross-product semantics
  + JS shim for joint widgets are deferred to v2.
- **Path Y subgraph re-execution.** v1 re-runs the whole notebook per
  value; v2 will use marimo's dataflow graph to re-execute only the
  affected subgraph (10–100× speedup for notebooks with expensive
  imports / data loads).
- **`mo.ui.range_slider`.** Two-handle widget with pair-valued state
  needs more design.

### Demo

The `Authoring → Static reactivity demo` page in this book shows the
feature live. View its source on GitHub to see exactly how the author
wrote it — there's nothing marimo-book-specific in the `.py`.

### When to use it (and when not to)

**Good fit:**
- Educational notebooks with "tweak this parameter and see what happens"
- Discrete dropdowns of options with cheap-to-compute outputs
- Single-slider plot explorations with ≤50 values

**Bad fit:**
- Continuous sliders that need fine-grained interactivity (use
  [WASM mode](#wasm-render-mode))
- Notebooks where every cell is expensive (build time × N values).
  Wrap the expensive cell in
  [`mo.persistent_cache`](authoring.md#caching-slow-cells-mopersistent_cache)
  so subsequent precompute runs hit the cache.
- Multi-widget cross-products with shared downstream cells (v2)

### Build cost

- **First export** is the static fallback render — paid regardless.
- **Each additional value** = one full notebook re-execution. Use
  `max_seconds_per_page` to bound this; the orchestrator extrapolates
  after the first export and aborts if projected runtime exceeds.
- **The build cache** (v0.1.0a4) interacts with precompute correctly:
  toggling `precompute.enabled` invalidates affected pages.

## WASM render mode

For pages that need *full* Python reactivity — continuous sliders,
arbitrary user input, real downstream re-execution — opt in per page:

```yaml
toc:
  - file: content/intro.py            # static (default)
  - file: content/explorer.py         # full WASM
    mode: wasm
```

Or for a whole book:

```yaml
defaults:
  mode: wasm
```

**What it does.** The preprocessor routes the page through marimo's
[`MarimoIslandGenerator`](https://docs.marimo.io/api/exporting/#marimo.MarimoIslandGenerator).
At first paint the browser downloads marimo's frontend bundle (~5 MB
gzipped, jsdelivr CDN) plus Pyodide (~30 MB, lazy). Cells then become
natively reactive — sliders work continuously, every cell re-runs on
input change, no precompute caps apply.

**When to use.** Per-page opt-in is the recommended pattern: leave most
chapters static for instant first paint, flip `mode: wasm` only on
the few that genuinely need full reactivity.

**When NOT to use.** Compute-heavy notebooks fare badly under WASM —
joblib's parallel backend doesn't run efficiently in Pyodide, and big
NumPy/Pandas/scientific stacks have slow first-import in the browser.
For one-shot expensive computations,
[`mo.persistent_cache`](authoring.md#caching-slow-cells-mopersistent_cache)
on a static page is faster end-to-end.

**Caveats.**
- First page load is heavy (~30 MB Pyodide download, cached after).
- Not every Python package is in Pyodide's package set — check
  [pyodide.org/packages](https://pyodide.org/en/stable/usage/packages-in-pyodide.html).
- File system access via relative paths needs care: marimo's
  `__file__` and `mo.notebook_dir()` resolve to internal paths under
  `MarimoIslandGenerator`. If a notebook does
  `Path(__file__).parent / "data"` it won't find the file. Use a
  cwd-walk pattern instead, or wait for
  [marimo-team/marimo#9391](https://github.com/marimo-team/marimo/issues/9391).

The `Authoring → WASM demo` page in this book is a working example.

## ePub / other formats?

Not supported as a flag yet. **Recipe via [pandoc](https://pandoc.org)
on the built site:**

```bash
marimo-book build
pandoc _site/intro/index.html _site/chapter1/index.html ... \
  -o book.epub \
  --metadata title="My Book" \
  --metadata author="Your Name"
```

If demand picks up, an `[epub]` extra is on the roadmap. File an
issue with your use case.

## Build performance reference

Approximate timings on a modern laptop (M-series Mac, no sandbox mode):

| Operation | Time |
|---|---|
| Parse `book.yml`, validate TOC | <50 ms |
| Render one Markdown page | <10 ms |
| `marimo export` for one notebook (no widgets) | ~500 ms |
| `marimo export` for one notebook (heavy anywidgets) | ~2 s |
| Full `mkdocs build` for ~20 pages | ~500 ms |
| `social_cards` rendering | ~250 ms / page |
| `pdf_export` rendering | ~600 ms / page |
| `check_external_links` (per outbound URL) | 1–3 s |

`sandbox` mode adds ~5–10 s per notebook the first time (provisioning
a fresh `uv` env); subsequent runs hit the `uv` cache and are fast.
See [Authoring → Dependencies](dependencies.md) for the full sandbox
walkthrough.
