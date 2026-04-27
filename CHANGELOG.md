# Changelog

All notable changes to `marimo-book` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.3] — 2026-04-27

### Fixed

- **Static reactivity demo: cell content rendered as raw markdown when
  the slider was moved off its default value.** The precompute lookup
  table embedded in each page stored marimo's markdown export of each
  cell, but the JS shim sets `el.innerHTML = delta[idx]` directly —
  pasting raw markdown into the DOM. The default-value cells looked
  correct because they live in the page body and pass through mkdocs;
  every other value's cells came out as ` ```python … ``` ` and
  `| Scale | Value | |---|---| …`. The preprocessor now pre-renders
  each delta to HTML at build time using the same Python-Markdown
  extension list mkdocs is configured with, so the lookup-table values
  match what mkdocs emits for the body. Latent since precompute first
  shipped; only obvious after 0.1.2's inline-controls placement
  (#19) put the slider next to the cells it drives.

## [0.1.2] — 2026-04-27

Patch release: Jupyter-Book-style sidebar logo, header launch buttons
with icons, automatic `index.md` promotion so the home page just works,
Plotly figure hydration, and a handful of related rendering fixes.

### Added

- **`logo_placement: sidebar`** in `book.yml` — renders the logo as a
  prominent banner above the left nav (Jupyter-Book chrome) instead of
  the small Material header icon. Default stays `header`. CSS lives in
  a separate stylesheet that's only emitted when the flag is set.
- **Header launch buttons** (default). The molab / GitHub / Download
  row now mounts in Material's top header bar as icon-only buttons via
  a small JS shim, with a screen-reader-only label. The legacy
  `placement: page` mode is still available for the over-the-title row.
- **Plotly hydration**. Marimo emits each plotly figure as a custom
  `<marimo-plotly>` element with the figure spec inlined as JSON. The
  preprocessor now rewraps as `<div class="marimo-book-plotly">` and
  `marimo_book.js` lazy-loads Plotly.js from jsdelivr on first encounter
  to render fully interactive charts (zoom / pan / hover).
- **Auto-promote first TOC entry to `index.md`**. Without this, mkdocs
  serves nothing at the site root; the header logo's `/` link 404'd.
  Authors don't need to know about the convention — whatever entry is
  first in the TOC becomes the home page transparently.
- **Empty-section tolerance**. Sections with `children: null` (or no
  children) no longer trip pydantic; they're silently dropped from the
  nav so authors can stub out placeholders mid-draft.

### Fixed

- **Sidebar logo overlap** with the chapter list when scrolled. The
  Material default sticky title had no background; chapters scrolled
  *behind* the logo. Now opaque + capped at 96 px with `z-index: 1`.
- **Dark-mode primary turning violet** despite a green `book.yml`
  palette. `_inject_palette` now writes the user's primary/accent into
  *both* schemes with `!important`; extra.css's defaults drop the
  `!important` so the user palette wins.
- **Header / sidebar logo alignment**: 1.1 rem left padding so the
  sidebar logo sits at the same x as the header's site title (within
  ~2 px).
- **Escaped `<marimo-*>` element leaks**. `marimo export ipynb`
  sometimes emits anywidget / plotly / slider tags HTML-escaped under a
  text/markdown mime; the preprocessor now detects the broader prefix
  list and routes through the rewriter so the raw escaped tag never
  leaks as visible text.
- **Inline precompute controls**. The widget control mount used to
  splice at the top of the page body, often far from the cells it
  drove (e.g. ICA's brain-plot slider was hundreds of px above the
  brain plot). Now lands immediately above the first reactive cell.
- **Orphan precompute temp dirs**. The precompute pipeline's
  `TemporaryDirectory(dir=py_path.parent)` leaks `marimo_book_precompute_*`
  directories when the marimo subprocess is interrupted (Ctrl-C,
  watcher restart, OOM). Added `cleanup_orphan_precompute_dirs` that
  sweeps these at the start of every build.
- **Drawdata anywidget demo on the docs site** rendered as a
  `ModuleNotFoundError` because CI didn't have `drawdata` installed.
  Added the install step to the docs workflow.

### Changed

- **Material's GitHub source widget** (the version + stars + forks
  card next to `repo_url`) is hidden via CSS — redundant with the new
  GitHub icon button. `repo_url` is still set in `mkdocs.yml` so
  per-page "Edit on GitHub" links work.
- Removed Material's separate Print button (Cmd-P is universal).

## [0.1.1] — 2026-04-26

Patch release: two render-path bug fixes plus a working drawdata
anywidget demo on the docs site, and a top-level `CNAME` convention
so the docs site can ship under a custom domain.

### Fixed

- **Anywidget render under `text/markdown` mime.** `marimo export
  ipynb` sometimes downgrades an anywidget HTML bundle to a
  `text/markdown` blob with the `<marimo-anywidget>` tag fully
  HTML-escaped (`&lt;marimo-anywidget`). The mime-bundle picker now
  detects that, unescapes, and routes through the existing rewriter
  so the static mount `<div>` is emitted. Without this, anywidgets
  authored via third-party libraries like
  [drawdata](https://github.com/koaning/drawdata) would render as
  visible escaped HTML text instead of the live widget.
- **Precompute slider boot race.** Material's `document$` is an
  RxJS `Subject` (not a `BehaviorSubject`) — subscribers added after
  its initial emission miss it. Combined with the `defer`'d shim
  script tag, direct page loads occasionally raced past the initial
  `document$` event, leaving the precompute control mount empty (and
  hidden by `:empty { display: none }` CSS, so invisible to authors).
  Boot is now belt-and-suspenders: run once via `DOMContentLoaded` /
  immediate, *and* subscribe to `document$` for instant-nav swaps.
  All boot work is idempotent.

### Added

- **Top-level `CNAME` convention.** Drop a `CNAME` file at the book
  root next to `book.yml`; the preprocessor copies it into the
  staged docs tree so mkdocs ships it as `_site/CNAME`. GitHub Pages
  preserves the custom-domain setting on every redeploy.
- **drawdata anywidget demo** in the docs site
  (`Authoring → Anywidget demo: drawdata`) — a live click-to-draw
  scatter canvas that proves the static anywidget pipeline renders
  third-party widgets correctly.

### Changed

- `marimobook.org` is the canonical docs URL (was
  `ljchang.github.io/marimo-book/`).

## [0.1.0] — 2026-04-26

**First stable release.** marimo-book is suitable for real production
use. The `book.yml` schema is frozen within the 0.1.x series — fields
may be added (additive, backward-compatible) but no field will be
removed or have its meaning changed without a major version bump.

This release ships per-page WASM render mode via marimo's islands
runtime, completing the render-mode story: every page can opt into
its preferred reactivity model (static / static + precompute / WASM)
based on the chapter's needs, with the rest staying fast and light.

### Added — WASM render mode (per-page opt-in)

- **`mode: wasm`** as a per-entry override in `book.yml` TOC entries.
  When set, the page is rendered through marimo's
  `MarimoIslandGenerator` instead of our static `cells_to_markdown`
  pipeline. Marimo's runtime + Pyodide load in the browser at first
  paint; cells become natively reactive, no precompute caps apply,
  continuous sliders work as you'd expect from a real notebook.
- `book.defaults.mode` is now widened to `Literal["static", "wasm"]`
  for whole-book defaults; `wasm` per-entry override coexists.
- `Book` config gains `FileEntry.effective_mode(default)` helper that
  resolves the per-entry override against the book-wide default.
- New module `src/marimo_book/transforms/wasm.py` with
  `render_wasm_page()` — invokes `MarimoIslandGenerator.from_file()`,
  awaits `build()`, returns `render_head() + render_body(style="")`
  ready to splice into the staged page. Per-page head injection (no
  global `extra_javascript` pollution).
- Static reactivity (`precompute.enabled`) is automatically a no-op
  for WASM pages — marimo's runtime handles reactivity natively, so
  there's no point in our build-time precompute pipeline.
- New CSS in `assets/extra.css` overriding marimo island fonts to
  Geist (matches our static theme), suppressing per-island margins,
  hiding marimo's loading spinner. Phase 1 styling — pixel-perfect
  match is a polish pass.
- New live demo chapter `docs/content/wasm_demo.py` configured with
  `mode: wasm` in the docs site TOC. Demonstrates a continuous
  `mo.ui.slider(1, 100)` driving live Python computation in the
  browser — the same widget call would render as static-only on a
  non-WASM page (no precompute candidate without an explicit step).

### Asset hosting

Marimo islands runtime + style are loaded from jsdelivr CDN by default
(matches what `MarimoIslandGenerator.render_head()` emits and what we
already do for Google Fonts + MathJax). Pyodide loads on demand from
its own CDN inside marimo's bundle. Self-hosting is on the roadmap
for the privacy-conscious / offline case but not yet implemented.

## [0.1.0a6] — 2026-04-26

Multi-widget reactivity + dartbrains-driven fixes. Static reactivity
now handles independent and joint (cross-product) multi-widget pages.
Multi-line widget call definitions are recognised. The all-kwargs
slider style (`mo.ui.slider(start=A, stop=B, step=N)`) — marimo's
recommended form — now produces precompute candidates. Validated by
real testing on the dartbrains course site.

### Added — joint multi-widget + multi-line widget calls

- **Joint multi-widget precompute (cross-product).** Widgets that share
  downstream cells now precompute together via the cartesian product of
  their values. Each joint group emits a single
  `<script class="marimo-book-precompute-group">` metadata + lookup
  table block keyed by `JSON.stringify([v1, v2, ...])`. The JS shim
  reads every widget in the group on each input event, constructs the
  combo key, and swaps cells together. Bounded by
  `max_combinations_per_page` — a 9-widget group with 5 values each is
  1.95M combos and trips the cap; 2-widget groups with ~10 values each
  fit comfortably.
- Connected-components grouping (`_group_widgets_by_downstream`):
  union-find pass over the cell→widget map. Independent widgets stay
  in singleton groups (existing behaviour); widgets sharing any
  downstream cell get unioned into one joint group.
- **Multi-line widget call substitution.** Widget calls spanning
  multiple lines (the dartbrains pattern: `mo.ui.slider(\n    start=0,
  \n    stop=10,\n    step=1,\n)`) now substitute correctly. The
  splice replaces the entire `(start_line, col)`–`(end_line, end_col)`
  range with the unparsed call expression — multi-line call collapses
  to one line in the temp source consumed by `marimo export` (never
  shown to the user).

### Added — multi-widget independent precompute (1/2)

- **Multi-widget independent precompute.** Lifts the v0.1.0a5
  single-widget-per-page restriction. Pages with N discrete widgets
  whose downstream cells are **disjoint** now precompute each widget
  independently. Each widget gets its own input control + lookup
  table, and the JS shim limits cell swaps to the widget that drives
  them. Joint widgets (sharing a downstream cell) still cause the
  whole page to render static with a clear "joint multi-widget
  precompute is deferred" warning.
- AST scanner now recognises `mo.ui.slider(start=A, stop=B, step=N)`
  with all-kwargs form (marimo's recommended style and what dartbrains
  uses everywhere). Continues to recognise positional and
  start/stop-positional + step-kwarg forms.
- New `estimate_renders_independent()` helper sums per-widget renders
  (1 + sum(values_i - 1)) instead of the cartesian product. The
  preprocessor uses this against `max_combinations_per_page` so the
  cap reflects realistic v1 cost — independent multi-widget pages no
  longer trip an astronomical cross-product number.
- Substitution failures (e.g. multi-line widget call definitions)
  surface as a clear `BuildReport.warnings` entry instead of
  silently skipping. Authors get told which widget couldn't be
  precomputed and why.

### Changed

- `precompute_page()` signature: takes `candidates: list[WidgetCandidate]`
  instead of a single candidate. Single-widget callers pass a
  one-element list; behaviour matches v0.1.0a5 for the 1-widget case.
- Per-widget script blocks (`<script class="marimo-book-precompute-widget">`,
  `<script class="marimo-book-precompute-table">`) and control mounts
  (`<div class="marimo-book-precompute-control">`) now carry a
  `data-precompute-widget="varname"` attribute used to pair them on
  multi-widget pages.
- Reactive cells gain a `data-precompute-widget="varname"` attribute
  alongside `data-precompute-cell="N"` so the JS shim limits swaps
  to cells controlled by the changed widget.

### Validated on dartbrains

Cache (v0.1.0a4) gives a **31× speedup** on dartbrains warm rebuild
(107s cold → 3.4s warm; 20 notebooks all cache-hit). Multi-widget
independent works on simple cases; on dartbrains specifically, 4 of
4 widget-heavy chapters either trip the disjointness check (joint
widgets, deferred to v2) or have value counts above the default cap.
The unlock for dartbrains will be **joint multi-widget cross-products**
(deferred), and **multi-line widget call support** for chapters like
ICA.

## [0.1.0a5] — 2026-04-25

Static reactivity for marimo's discrete UI widgets ships in two
PRs (#6 + #7). Authors enable `precompute.enabled: true` in `book.yml`
and discrete widgets (`mo.ui.slider(steps=[...])`,
`mo.ui.dropdown(options=[...])`, `mo.ui.switch()`,
`mo.ui.checkbox()`, `mo.ui.radio(options=[...])`) get real
client-side interactivity backed by build-time per-value rendering —
no Python kernel at runtime. Caps cap compute time and bundle size;
v1 supports single-widget pages.

### Added — static reactivity execution (2/2)

- Per-value re-export pipeline: when `precompute.enabled: true` and a
  page has a single discrete-widget candidate, the preprocessor runs
  `marimo export ipynb` once per non-default value (substituting the
  widget's `value=` via AST surgery in a temp source), captures
  per-cell HTML, and stores the diff against the base render as a
  JSON lookup table embedded in the page.
- `max_seconds_per_page` cap is now wall-clock-enforced: the first
  re-export's runtime is extrapolated; if projected total exceeds the
  budget, remaining values are skipped and the page renders static.
- `max_bytes_per_page` cap is now byte-enforced after each combination
  is captured.
- Reactive cells (those whose output differs across at least one value)
  are wrapped in `<div class="marimo-book-precompute-cell" ...>` for
  client-side targeting. Cells whose output is identical across all
  values are not stored — bundle stays bounded by what actually changes.
- Client-side JS shim (`assets/marimo_book.js`): renders the input
  control (range slider, select, or checkbox depending on widget kind),
  reads the embedded lookup table, and swaps reactive cell HTML on
  input — smooth, no page reflow, headers/sidebar/scroll position all
  preserved.
- New CSS for `.marimo-book-precompute-control` and the input controls
  (Material-themed, accent-coloured slider, tabular-numerics for the
  value label).
- New "Static reactivity" section in `docs/content/building.md`
  documenting the feature, the detection rules, the caps, and the v1
  limitations (single-widget pages only, Path-X execution path).
- New live demo chapter at `docs/content/precompute_demo.py` —
  temperature-conversion slider that swaps a Markdown table per value.
  Visible at `Authoring → Static reactivity demo` on the docs site
  with `precompute.enabled: true`.
- `Preprocessing OK` summary now reports precompute counts:
  `(14 pages, 13 rendered, 0 cached, 1 precomputed, 0 skipped)`.
- v1 limitation: multi-widget pages render every widget static with a
  warning. Multi-widget cross-products + Path-Y subgraph re-execution
  are deferred to v2 / when WASM render mode lands.

### Added — static reactivity foundation (1/2)

- `book.yml` `precompute` block (off by default) — opt-in static
  reactivity for discrete marimo UI widgets. Five fields:
  `enabled`, `max_values_per_widget` (default 50),
  `max_combinations_per_page` (200), `max_seconds_per_page` (60),
  `max_bytes_per_page` (10 MB), `exclude_pages` ([]).
- AST scanner (`src/marimo_book/transforms/precompute.py`) that finds
  precompute candidates without executing the notebook. Recognises:
  `mo.ui.slider(steps=[...])`, `mo.ui.slider(start, stop, step=N)`
  (or 3 positional args), `mo.ui.dropdown(options=[...])`,
  `mo.ui.dropdown(options={...})`, `mo.ui.switch()`, `mo.ui.checkbox()`,
  `mo.ui.radio(options=[...])`. Continuous sliders without an explicit
  step are deliberately skipped (render static). Non-literal arguments
  (`mo.ui.dropdown(options=opts)`) are skipped — value sets must be
  statically extractable.
- Preprocessor preview pass: when `precompute.enabled: true`, every
  `.py` page is scanned, count caps are applied, and over-cap widgets
  are recorded as `BuildReport.warnings` ("rendered static") with the
  page + widget name + which cap was hit. `BuildReport` gains
  `widgets_precomputed` / `widgets_skipped` counters.
- Build cache `_book_signature` now includes the `precompute` block,
  so toggling the flag invalidates rendered notebooks correctly.

This is the foundation only — the actual per-value re-export pipeline
+ client-side JS swap shim ship in the next PR. Until that lands,
`widgets_precomputed` is a *would-precompute* count: useful for tuning
caps before paying for execution.

## [0.1.0a4] — 2026-04-25

Build-cache + PDF + docs release. Cuts repeat-build time on books
with non-trivial notebooks (the dartbrains use case) from minutes to
seconds.

### Added

- **Incremental build cache.** The preprocessor now caches `marimo
  export ipynb` outputs at `{book_root}/.marimo_book_cache/manifest.json`
  keyed by source content hash, marimo-book version, and relevant
  `book.yml` fields (`widget_defaults`, `defaults`, `dependencies`,
  `launch_buttons`, `repo`, `branch`, `toc`). Subsequent builds skip
  notebooks whose source hasn't changed. Typical edit-one-chapter
  rebuild on a 20-notebook book drops from "every notebook" to "only
  the edited one". Markdown entries are not cached (10 ms each, not
  worth the bookkeeping).
- `marimo-book build --rebuild` and `marimo-book serve --rebuild` —
  bypass the cache for the current invocation. Use when you changed
  something the cache can't detect (data file the notebook reads,
  env-mode dep upgrade). `--clean` continues to wipe `_site_src/` and
  now also wipes `.marimo_book_cache/`, which has the same effect.
- Build summary line now reports cache stats:
  `Preprocessing OK (13 pages, 11 rendered, 1 cached at _site_src).`
- `book.yml` `pdf_export: bool` flag — when true, emits the
  `mkdocs-with-pdf` plugin so the build produces a single
  `_site/pdf/book.pdf` rendered through WeasyPrint, with a "Download
  PDF" link injected into the footer. Cover metadata (title,
  subtitle, author, copyright) inherits from existing `book.yml`
  fields. Requires the new `marimo-book[pdf]` extra; needs the same
  `libcairo2` / `libpango` system deps as `social_cards`.
- New "Building" page in the docs (`content/building.md`) — full
  reference covering the two-stage build pipeline, every CLI command
  with all flags, the five opt-in feature flags with their extras,
  the `_site_src/` and `_site/` output layouts, an ePub recipe via
  pandoc, and approximate build-performance numbers. Now also covers
  the build cache + invalidation rules.

## [0.1.0a3] — 2026-04-25

Visual + authoring overhaul plus a release-flow modernisation.

### Added

- `book.yml` `cross_references: bool` flag opts into the
  `mkdocs-autorefs` plugin so authors can write `[Heading text][]` and
  have it resolve to whatever page has that heading — the MkDocs analog
  of MyST `{ref}`. Requires the new `marimo-book[autorefs]` extra.
- `book.yml` `include_changelog: bool` flag — when true, the
  preprocessor copies `CHANGELOG.md` from the book root into the staged
  docs tree and appends a "Changelog" entry to the nav. Single source
  of truth: the same file PyPI links to also becomes a docs page.
- Default stylesheet (`assets/extra.css`) modernized: zinc neutrals,
  near-black dark scheme (`#0a0a0a`), Geist Sans + Geist Mono via
  `theme.font`, indigo accent on h1 / header title, uppercase tracked
  section labels in left sidebar + right TOC, hairline footer that
  matches page bg in both schemes. Carries forward to zensical.
- README badges (PyPI version, Python versions, CI, License, Docs).
- Live admonition / math / table / code examples on the Authoring page.
- Cross-references documentation on the Authoring page (page-to-page,
  anchors, abbreviations, snippets, autorefs).
- `release-drafter` workflow + config — every merged PR updates a
  draft GitHub Release; tagging publishes it. Categorises by PR label
  (Added / Changed / Fixed / Removed / Documentation / Build & CI).

### Changed

- **Versioning:** switched to `hatch-vcs` for dynamic versions derived
  from git tags. `pyproject.toml` no longer carries a hard-coded
  `version`; tagging `v0.1.0a3` is sufficient to publish a wheel
  versioned `0.1.0a3`. `src/marimo_book/__init__.py` reads
  `__version__` via `importlib.metadata`. Eliminates the version-skew
  bug class (3 files no longer need to stay in sync per release).
- `PUBLISHING.md` rewritten around the new flow: tag-driven release,
  optional CHANGELOG-date PR, release-drafter populating release notes.

### Removed

- **Breaking:** MyST migration transforms (`{download}` role rewrite,
  `:::{glossary}` fence stripping). marimo-book now uses Material's
  Markdown dialect exclusively. Books written for marimo-book have
  always used Material syntax (`!!! note` admonitions, `[label](page.md)`
  links); the removed transforms only affected content ported from
  Jupyter Book. To migrate: replace `{download}\`text <path>\`` with
  `[text](path)` and remove `:::{glossary}` / `:::` fence markers (the
  inner definition lists pass through Material's `def_list` natively).

## [0.1.0a2] — 2026-04-24

Metadata + ergonomics pass on top of 0.1.0a1.

### Added

- `book.yml` gains two fields:
  - `url` — canonical public URL, emitted as mkdocs `site_url` so the
    social plugin and sitemap.xml get fully-qualified paths.
  - `social_cards: bool` — opts into Material's `social` plugin for
    auto-generated OpenGraph / Twitter preview images per page. Requires
    the new `marimo-book[social]` extra (`pip install
    'marimo-book[social]'`) which pulls `mkdocs-material[imaging]` +
    Pillow + cairosvg.
- `pyproject.toml` `Documentation` project URL now links directly to
  the docs site, so PyPI's sidebar gains a "Documentation" link in
  addition to Repository / Issues / Changelog.

### Changed

- CI + docs deploy workflows install `libcairo2` / `libpango` on
  Ubuntu so the social plugin's SVG→PNG rendering works.

### Fixed

- `info.license` still reports `None` on pypi.org JSON API (this is a
  Warehouse-side transition from `License` → `License-Expression` per
  PEP 639). The real PyPI page and the wheel METADATA both report MIT
  correctly.

## [0.1.0a1] — 2026-04-24

First alpha release. Usable end-to-end for single-book sites.

### Added

**CLI** (`marimo-book ...`)

- `new <dir>` — scaffold a new book (book.yml, content/, .gitignore,
  .github/workflows/deploy.yml, README). `--force` to write into
  non-empty directories.
- `build` — preprocess + emit static site to `_site/`. `--strict` fails
  on warnings; `--clean` blows away prior build artifacts first.
- `serve` — dev server with live reload. Runs an initial build, spawns
  `mkdocs serve`, and a watchdog observer rebuilds on changes to
  `content/` or `book.yml`.
- `check` — validate `book.yml` + referenced files without building.
- `clean` — remove `_site/`, `_site_src/`, `.marimo_book_cache/`.

**Config** (`book.yml`)

- Pydantic v2 schema with readable errors for unknown keys.
- Discriminated-union TOC (`file:` / `url:` / `section:` + `children:`).
- Author metadata, branding (logo, favicon, palette, fonts), launch
  buttons, bibliography paths, analytics (Plausible / Google), per-page
  render defaults, per-widget-class default state.
- Top-level `shell:` reserved for future `zensical` / `jinja` targets.

**Preprocessor transforms**

- `marimo_export` — `.py` → Markdown + inline HTML via
  `marimo export ipynb --include-outputs`. Handles hide_code, mime bundles
  (text/html, text/markdown, image/png|jpeg|svg+xml, text/plain,
  streams, errors), and first-setup-cell elision.
- `callouts` — `<marimo-callout-output>` → Material admonition with the
  kind mapped (info/note/success/tip/warning/danger/failure/neutral).
- `anywidgets` — `<marimo-anywidget>` → `<div class="marimo-book-anywidget">`
  mount; AST-walks cell source to extract literal widget kwargs; merges
  with `book.yml` `widget_defaults`. Strips
  `<marimo-ui-element>` / `<marimo-slider>` / etc. wrappers around
  kernel-dependent controls that have no static analog.
- `md_roles` — `{download}\`label <path>\`` → `[label](path)`;
  `:::{glossary}` fence stripping.
- `link_rewrites` — `.ipynb` cross-refs → `.md` (when target exists);
  `../images/` → `images/` in both Markdown links and HTML attrs.

**Shell generator**

- `book.yml` → `mkdocs.yml` with Material theme, standard pymdownx
  extensions (arithmatex, admonition, blocks, details, highlight,
  superfences, tabbed, tasklist), sensible nav feature flags, and an
  `extra.css` derived from the book's palette.

**Runtime shim** (`assets/marimo_book.js`)

- Minimal anywidget-compatible model loader. At page load, finds every
  `.marimo-book-anywidget` mount, decodes the inlined ES module from
  `data-js-url`, and calls `module.default.render({model, el})` with a
  seeded model. Works with Material's instant-navigation via
  `document$.subscribe`.

### Verified

- Full test suite: 46 passing across config, transforms, CLI, and watcher.
- End-to-end dartbrains build (34 TOC entries, 20 marimo notebooks):
  0 preprocessor errors, 2 cosmetic mkdocs warnings (both broken-link
  issues in dartbrains source content, not tool bugs).
- Widget-heavy chapter (MR_Physics.py, 9 anywidgets) renders and animates
  in a browser without marimo's frontend runtime.

### Known limitations

- No WASM / hybrid render modes yet (static only).
- No dependency-graph-aware incremental cache; every rebuild is a full
  rebuild.
- MyST cross-refs with `{ref}`, `{numref}`, `{eq}`, `{cite}`, etc. are
  stripped through unchanged (no usage in any book we've migrated yet).
- Material for MkDocs is entering maintenance mode in ~12 months;
  `marimo-book` is explicitly designed to port to [zensical](https://zensical.org)
  when it stabilises (same `mkdocs.yml`, different build command).
