# CLAUDE.md

Guidance for Claude Code (and other AI assistants) working in this repo.

## What this project is

`marimo-book` is a Jupyter-Book-style static site generator for marimo
notebooks. It reads a directory of `.md` and marimo `.py` files plus a
`book.yml` config and emits a polished documentation site built on
Material for MkDocs (and, eventually, on its Rust successor zensical —
the architecture is shell-agnostic).

## Architecture in one paragraph

`book.yml` → preprocessor (`src/marimo_book/preprocessor.py`) → staged
tree at `_site_src/` (Markdown + inline HTML, plus a generated
`mkdocs.yml`) → `mkdocs build` → `_site/`. The preprocessor never
shells out to mkdocs; it just emits artifacts mkdocs can consume. This
keeps the shell swappable. The CLI (`src/marimo_book/cli.py`) glues
the preprocessor + `mkdocs build`/`serve`.

## Common commands

```bash
# Setup (in repo)
uv pip install -e '.[dev,linkcheck,social,autorefs]'

# Tests + lint
pytest -q
ruff check src/ tests/
ruff format --check src/ tests/

# Build the self-hosted docs (this repo's own book)
marimo-book build -b docs/book.yml

# Live-reload dev server for the docs
marimo-book serve -b docs/book.yml   # http://127.0.0.1:8000/marimo-book/

# Build a brand-new book scaffold
marimo-book new ~/my-book
cd ~/my-book && marimo-book serve
```

When `marimo-book serve` won't pick up CSS changes after a `build`,
it's the in-memory mkdocs cache. **Kill and restart serve** rather
than waiting for auto-reload.

## Release flow (the important one)

Releases are tag-driven via `hatch-vcs`. There is **no `version` field
in `pyproject.toml`** — the version is the latest `v*` git tag.

`.github/workflows/publish.yml` triggers on **`push: tags: ["v*"]`**
(not on publishing a GitHub Release). So the act that ships a release
is **pushing a `v*` tag**; `hatch-vcs` reads the tag, builds a wheel
versioned exactly to it (e.g. `v0.1.18` → `0.1.18`), and ships it to
PyPI via OIDC Trusted Publisher.

To cut a release:

1. Open a tiny PR that dates the `[Unreleased]` section in
   `CHANGELOG.md` to today (one-line change, e.g.
   `## [0.1.18] — YYYY-MM-DD`). Merge it.
2. Tag merged `main` at that commit **via `gh release create`** — this
   creates+pushes the `v*` tag (which fires `publish.yml` → PyPI) **and**
   creates the matching GitHub Release object, so the repo's Releases page
   stays current:

   ```bash
   git checkout main && git pull
   # Notes = that version's CHANGELOG section.
   gh release create v0.1.21 --target main --title v0.1.21 \
     --notes "$(awk '/## \[0\.1\.21\]/{f=1;next} /^## \[/{if(f)exit} f' CHANGELOG.md)"
   ```

   Watch the publish run: `gh run watch --repo ljchang/marimo-book`
   (or the Actions tab). A bare `git tag … && git push origin v0.1.21`
   still works and still publishes to PyPI — but it leaves **no** GitHub
   Release object, which is why the Releases page used to lag. Prefer
   `gh release create`.

That's it. **Never push version edits directly to main**, and never
push a `v*` tag you don't intend to publish — the tag *is* the
release trigger. The version lives in exactly one place: the git tag.

**Note (2026-06): `gh release create` is now the standard.** Earlier
releases (`v0.1.12`–`v0.1.20`) were cut by bare tag push and had no
GitHub Release object; they've since been backfilled from the CHANGELOG,
so every `v0.1.x` tag now has a Release. Use `gh release create` going
forward so this never drifts again. The old `release-drafter` draft
(stuck at `v0.1.11`) is **not** part of the live flow — ignore it.

See `PUBLISHING.md` for full detail (one-time PyPI setup, label
conventions for release-drafter categorisation, yanking, etc.).

## Branch protection / direct main pushes

Pushes to `main` are blocked by the harness for safety. All work goes
through PRs. CI must be green before merge:

- `test (3.11/3.12/3.13)` — `pytest` + `ruff check` + `ruff format --check`
- `build` — sdist + wheel build with required-files check
- `docs` — `marimo-book build -b docs/book.yml --strict`

If a PR introduces a new optional extra (like `[autorefs]`), update
both `.github/workflows/ci.yml` and `.github/workflows/docs.yml` to
install it (the docs job needs every extra the docs site uses).

`marimo-book check` (build-free doctor) lives in `src/marimo_book/checks.py`.
Keep it fast and side-effect-free: no notebook execution, no subprocesses,
no network. When adding a feature flag with a new extra, add its probe to
`_FEATURE_EXTRAS` there so `check` catches the missing install.

## Build strictness and execution bounds (since 0.1.27)

- **`build --strict` fails when a notebook cell raises.** The traceback
  still renders into the page (authoring aid), but it lands in
  `report.errors` under strict. Non-strict builds, blog posts, and
  `marimo-book render` warn. Opt out per TOC entry with
  `allow_errors: true` (for lessons that demo exceptions). The verdict
  survives caching: raising cells are recorded in the transient cache
  AND in `_rendered/` manifest entries and replayed on hits — do not
  remove that replay or a cached strict run will silently pass. WASM
  pages are exempt (islands pipeline produces no ipynb error outputs).
  The docs CI job installs `drawdata anywidget` because without them
  the demo notebooks raise and now fail the strict docs build.
- **`defaults.execution_timeout`** (seconds, default 600, `null`
  disables) bounds every notebook execution: `marimo export`
  subprocesses AND the in-process WASM island build. It is deliberately
  **excluded from `_book_signature` and `_render_body_signature`** — it
  can abort a render but never change its output, so tuning it must not
  invalidate caches or committed `_rendered/` bodies. Keep any future
  "how long/how" knobs out of those signatures too.

## Feature flags users can opt into via `book.yml`

| Flag | Effect | Extra needed |
|---|---|---|
| `social_cards: true` | Material's `social` plugin auto-generates per-page OG/Twitter card PNGs | `marimo-book[social]` (pulls Pillow + cairosvg, ~20 MB; needs system `libcairo2 libpango-1.0-0 libpangocairo-1.0-0`) |
| `cross_references: true` | `mkdocs-autorefs` resolves `[Heading text][]` to whichever page has that heading (MyST `{ref}` analog) | `marimo-book[autorefs]` |
| `check_external_links: true` | `htmlproofer` validates external URLs at build (slow; CI-only) | `marimo-book[linkcheck]` |
| `include_changelog: true` | Preprocessor copies `CHANGELOG.md` from book root (or its parent) into the staged tree and appends a "Changelog" entry to the nav | None |
| `bibliography: [refs.bib]` (+ `cite_style: apa\|numbered`) | Native pandoc-style citations: `[@key]` in `.md` pages and notebook prose renders as linked inline citations + a per-page References section (`\bibliography` marker controls placement). Implemented in `transforms/citations.py` at **finalize time** (like link rewrites), so `.bib` edits never invalidate cached renders. NOT an mkdocs plugin — `mkdocs-bibtex` is archived + needs pandoc; native keeps it shell-agnostic. Skips wasm/precompute-spliced bodies and blog posts (v1). `check` errors on missing `.bib`, warns on unknown keys. | None (pybtex is a base dep) |
| `pdf_export: true` | `mkdocs-with-pdf` renders the whole book to `_site/pdf/book.pdf` via WeasyPrint and adds a "Download PDF" link to the footer | `marimo-book[pdf]` (same cairo/pango system deps as `[social]`) |
| `precompute.enabled: true` | Detects discrete `mo.ui.*` widgets, re-exports per value, ships a JSON lookup table embedded in the page; JS shim swaps reactive cells on widget input. Caps in `precompute.{max_values_per_widget, max_combinations_per_page, max_seconds_per_page, max_bytes_per_page}`. Multi-widget independent + joint cross-products both supported (since v0.1.0a6). Auto-no-op on WASM pages. | None |
| `defaults.mode: wasm` (or per-entry `mode: wasm`) | Page rendered via `MarimoIslandGenerator`. Marimo's runtime + Pyodide load in the browser; cells become natively reactive, continuous sliders work, no precompute caps. Heavy first paint (~30 MB Pyodide download, cached after first visit). Per-page opt-in is the recommended pattern — leave most pages static for fast loads, enable wasm only on chapters that need full interactivity. **For these pages the build also ships a micropip bootstrap** as an extra, anchor-less cell inside marimo's islands JSON payload (`<script type="application/vnd.marimo.islands+json">`, marimo ≥ 0.24; built by `build_bootstrap_payload` in `transforms/wasm.py`), with every user cell's payload code prefixed by `_ = marimo_book_micropip_done` so marimo's dataflow runs the bootstrap first. The install list (`wasm_install_packages` in `transforms/pep723.py`) is import-derived deps ∪ the notebook's own PEP 723 block, minus Pyodide-bundled packages (from marimo's lockfile resolver; honours `MARIMO_PYODIDE_LOCK_FILE`, cached per Pyodide version under `.marimo_book_cache/`, unreadable ⇒ no filtering). `marimo_book.js` re-hydrates mounts on `marimo-island-source-changed` because the runtime materializes the payload after Pyodide boots. The islands runtime only micropip-installs packages listed in a column-zero PEP 723 block of the notebook file it synthesizes from cell code, and never carries that block over (marimo-team/marimo#9778) — Pyodide-bundled packages auto-load via `loadPackagesFromImports`, but pure-Python PyPI-only deps (`nltools`) silently fail without the install. The executed/staged source is NOT modified for this any more (pre-0.1.31 it was AST-injected, which round-tripped every WASM page with PyPI-only deps through `ast.unparse`; the title hoist still stages an `ast.unparse`d copy for H1-led notebooks, and that is now the only source rewrite on the WASM path). The sentinel must not start with an underscore (marimo makes such names cell-local). Emitted only when that filtered list is non-empty. Tests set `MARIMO_PYODIDE_LOCK_FILE` to `tests/fixtures/pyodide-lock.json` (autouse fixture in `tests/conftest.py`) so nothing hits the network. | None (CDN bundle from jsdelivr by default) **anywidgets (marimo ≥ 0.24):** the module comes from the session view (`anywidget_esm_by_model` for islands, `_export_runner.py` for static/precompute) and is restored as `data-js-url` on the mount; after the kernel runs, marimo's runtime renders anywidgets itself — do not intercept runtime-emitted `<marimo-anywidget>` elements (see the comment in `marimo_book.js`). |
| `dependencies.auto_pep723: true` | Auto-generate `# /// script` PEP 723 blocks from each notebook's imports for *static + sandbox* pages too (WASM pages always get this regardless of the flag). Build stages a **sibling _file_** copy with the block injected (same directory as the source, so the notebook's `__file__` keeps its directory depth — a sub-tempdir would break `Path(__file__).resolve().parent.parent` root detection on WASM pages); user `.py` files are never modified. **Note**: only the PEP 723 block — the WASM micropip bootstrap is WASM-mode-only. Companion CLI `marimo-book sync-deps` writes blocks back into source for `molab` portability. Other knobs: `dependencies.{pin: env, extras: [...], overrides: {mod: dist}, requires_python: ">=3.11"}`. Module → distribution mapping uses marimo's own ~777-entry table; staged sibling files use prefix `marimo_book_pep723_` (precompute staging uses `marimo_book_precompute_`); both are created via `staged_sibling_file()` and swept by the orphan cleanup if a build is interrupted. | None |
| `blog.enabled: true` | Opt-in blog / news module on Material's `blog` + `tags` plugins (and `rss` when `blog.rss`, default on). Posts (`.md` or marimo `.py`) drop by convention into `<book>/blog/posts/` — **not** listed in the TOC. Metadata via YAML front-matter (`.md`) or a `# /// blog` block (`.py`, mirrors the PEP 723 `# /// script` shape); `date` defaults from a `YYYY-MM-DD-…` filename then git/mtime, `title` from the first H1. Bylines come from a **merged roster**: `book.yml` authors (auto-slugified ids) ∪ an optional `<book>/.authors.yml` (the explicit file wins on collision); an omitted `authors:` falls back to `blog.default_author` or the sole roster entry. Posts render through the normal pipeline (`.py` posts are static in v1) and a teaser `<!-- more -->` is auto-inserted (overridable). `marimo-book new-post "Title"` (`--notebook` for `.py`) scaffolds one. Knobs: `blog.{title, dir, rss, default_author}`. **Known limitation:** enabling the blog activates Material's site-wide `tags` plugin, which validates `tags:` front-matter on *every* page — so keep any `tags:` you add to non-blog content pages well-formed (a YAML list), or that page will fail the build. | `marimo-book[blog]` (RSS feed only — the blog/tags plugins ship with `mkdocs-material`) |
| `api_docs.enabled: true` | Auto-generates a Python "API Reference" nav section from a companion package's docstrings. Names packages by importable/dotted name and/or source `paths` (resolved relative to the book root; Griffe reads source without installing). The preprocessor stages one `::: pkg.module` page per public module (underscore-prefixed + `exclude` globs skipped) and splices a nested section into the nav; `mkdocstrings` renders them. Knobs: `api_docs.{packages, paths, docstring_style, title, dir, exclude, options, inventories}`. `options` passes through to the mkdocstrings Python handler (user keys win over marimo-book defaults). Shell-neutral staging + nav; only the plugin block is mkdocs-specific (ports to zensical by swapping that block). | `marimo-book[api]` (pulls mkdocstrings + mkdocstrings-python + Griffe) |

| `defaults.mode: cached` (or per-entry `mode: cached`) | Page outputs come from a committed `_rendered/` artifact instead of executing the notebook at build — the `execute: off` analog for heavy/GPU notebooks. Author runs `marimo-book render` (executes with real deps, commits rendered bodies under `_rendered/`, keyed by source hash **+** render config (`defaults`/`dependencies`/`widget_defaults`) + marimo-book version via `body_sig`); CI then `build`s with **zero** execution. Only the notebook *body* is committed (not buttons/link-rewrites), so changing `launch_buttons`/repo/TOC never invalidates it. `marimo-book render --check` exits nonzero when any committed output is stale (CI freshness gate); during `build` a stale/missing artifact warns and falls back to a live render for local authoring — **but `build --strict` makes it a hard error with no execution**, so CI never silently re-runs an unrendered notebook. See `RenderedStore` (`src/marimo_book/rendered_store.py`). | None |

| `shell: zensical` (or `build/serve --shell zensical`) | Runs [zensical](https://zensical.org) (Material's Rust successor) instead of `mkdocs` on the same generated `mkdocs.yml`. Verified against 0.0.62 (2026-09-13): page bodies byte-identical, `extra.css`/`marimo_book.js` hooks work (both variants keep Material's DOM; we emit `theme.variant: classic`), WASM islands + anywidgets run, ~0.6 s builds. **Zensical panics on absolute `docs_dir`/`site_dir` and rejects a `site_dir` outside the config's directory**, so `shell.py` emits `site_dir: site` (→ `_site_src/site/`) and `cli.py::_sync_zensical_output` mirrors it to `_site/`. It **silently ignores unsupported plugins even under `--strict`** — `social`, `blog`, `rss`, `htmlproofer`, `with-pdf` — so `checks.py::_ZENSICAL_UNSUPPORTED` errors on those combos; when upstream ships one, delete its row there and re-verify. `zensical serve --strict` is unsupported (never forwarded). Both shells run as `python -m <shell>`. Status/blockers: #105. The docs book keeps `shell: mkdocs` because it enables blog + social. | `marimo-book[zensical]` (also installed in the CI test job so `test_build_with_real_zensical` runs) |

All twelve are off by default in `marimo-book new` scaffolds.

### Custom domain (CNAME)

Drop a `CNAME` file at the book root (next to `book.yml`) containing
the apex domain (e.g. `marimobook.org`). The preprocessor copies it
into the staged docs tree so mkdocs ships it as `_site/CNAME` —
GitHub Pages then keeps the custom-domain setting on every redeploy.
DNS still has to be configured at the registrar (four `A` records on
the apex pointing at GitHub's Pages IPs, plus a `www` `CNAME` →
`<user>.github.io`). The `marimo-book` self-hosted docs use this
pattern for `marimobook.org` (see `docs/CNAME`).

## Bumping the marimo pin

`pyproject.toml` pins `marimo>=0.24,<NEXT_MINOR` (the floor is where the
islands JSON payload the WASM bootstrap rides on first shipped). The upper bound is
deliberate: marimo-book imports private marimo modules
(`transforms/pep723.py`: `_runtime.packages.module_name_to_pypi_name`,
`_utils.scripts`, `_pyodide.pyodide_constraints`; `transforms/wasm.py`:
`_schemas.islands`, `_templates`) and the build shells out to
`marimo export ipynb`. When a new marimo
minor ships, widen the bound only after this checklist passes against
it (all four ran clean for 0.24.1 on 2026-09-11):

1. `uv pip install --python .venv/bin/python 'marimo==X.Y.Z'` then
   `pytest -q` and `ruff check`.
2. `marimo-book build -b docs/book.yml --strict --rebuild` (real
   `marimo export` + `MarimoIslandGenerator`; needs the cairo env var
   from your shell on macOS).
3. `curl -I https://cdn.jsdelivr.net/npm/@marimo-team/islands@X.Y.Z/dist/main.js`
   — `render_head()` defaults `version_override` to the installed
   marimo version, so WASM pages 404 at runtime if the npm bundle for
   that version is missing.
4. Serve `docs/_site` and open `/wasm_demo/` in a browser: expect
   "Initializing 4 island(s)" and a `completed-run` message with zero
   console errors. **Also open `/widgets/`** and confirm the drawdata
   canvas renders — the anywidget path depends on marimo internals
   (`_export_runner.py`, session-view model notifications) that the
   strict build cannot check, and 0.24 broke it silently (#79). (One warning, "Failed to get version from mount
   config", comes from marimo's own islands bundle before any of our
   markup is read; hydration completes regardless, so ignore it.)

Read the upstream release notes for anything touching `_islands`,
`export ipynb`, `_utils/scripts`, `module_name_to_pypi_name`,
`_pyodide/pyodide_constraints`, `_schemas/islands`, or `_templates`.
Since 0.24 islands can also hydrate from a JSON payload
(`render_body(include_payload=True)`); marimo-book builds its own copy
of that payload — only for pages with PyPI-only deps — to carry the
micropip bootstrap cell (see `build_bootstrap_payload` in
`transforms/wasm.py`). Pages without such deps stay on the DOM-parsing
path, which upstream keeps as the supported fallback.

## Static rendering of non-HTML outputs

`transforms/marimo_export.py::_render_mime_bundle` picks one entry of each
cell's MIME bundle. Some marimo values have **no HTML form** and used to
vanish (#73): a bare `list`/`dict` is `application/json` with
`text/plain+<type>:` leaf/key markers, an Altair chart is
`application/vnd.vega(lite).v*+json`, and inside `mo.vstack` & co. both
become `<marimo-json-output>` / `<marimo-mime-renderer>` custom elements.
`transforms/mime_outputs.py` renders them statically (JSON → `<ul>` tree;
Vega → `<div class="marimo-book-vega" data-spec>` hydrated by
`marimo_book.js` via vega-embed from jsdelivr, same lazy-CDN pattern as
Plotly) and `rewrite_anywidget_html` rewraps the custom elements. When you
add support for another MIME type, bump `_RENDER_OUTPUT_VERSION` in
`preprocessor.py` so committed `_rendered/` bodies re-render. The docs
Widgets page demos both; the docs CI job installs `altair` for it.

## Theme + CSS

Default styling lives in `src/marimo_book/assets/extra.css` —
mono+violet-ink palette (zinc neutrals, indigo accent, near-black dark
mode). Inter / JetBrains Mono / Geist fonts wire through `theme.font`
in `book.yml` and Material loads them from Google Fonts automatically.
The palette is injected via CSS variables by the preprocessor; the
generated `mkdocs.yml` sets `primary: custom, accent: custom` so
Material's named-palette machinery doesn't fight us.

## Things to avoid

- **Do not edit `pyproject.toml`'s `version` field.** It doesn't exist
  — `dynamic = ["version"]` + hatch-vcs derives it from tags.
- **Do not edit `src/marimo_book/_version.py`.** It's auto-generated
  at build time (gitignored, excluded from ruff).
- **Do not hand-edit `{book_root}/.marimo_book_cache/manifest.json`.**
  It's the build cache; the next preprocessor run overwrites it. To
  force a full rebuild: `marimo-book build --rebuild` (preserves
  cache after the run) or `marimo-book clean` (wipes everything).
  Since cache v3 it stores pre-finalize *bodies* under
  `.marimo_book_cache/bodies/`; the key deliberately excludes the TOC,
  `launch_buttons`, `repo`, and `branch` because the finalize step
  (button row + link rewrites) re-runs against the cached body on every
  build. Precompute stats and cell errors are recorded per entry and
  replayed on hits — `_run_precompute` must never run on the hit path
  (the spliced output is already baked into the cached body).
- **Do not push directly to `main`.** The harness blocks this; route
  through a PR.
- **Do not bypass CI** with `--no-verify` or by skipping checks. Fix
  the failure root cause.
- **Do not re-publish to PyPI.** Yank a broken release; never delete.
- **Do not add MyST transforms back.** marimo-book uses Material's
  Markdown dialect exclusively (`!!! note`, `[label](page.md)`). MyST
  migration shims were removed in 0.1.0a3.

## Tests

`tests/` is the canonical test surface. Layout:

- `test_config.py` — pydantic schema round-trip
- `test_transforms.py` — small content transforms (callouts, launch buttons, marimo export)
- `test_preprocessor.py` — end-to-end Preprocessor.build() behaviour (changelog inclusion, etc.)
- `test_link_rewrites.py` — link rewriting transforms
- `test_dependencies.py` — dependency-mode resolution
- `test_cli_commands.py` — CLI invocation surface
- `test_watcher.py` — file-watcher used by `serve`
- `tests/fixtures/` — marimo notebook fixtures (excluded from ruff)
- `tests/phase0_spike/` — original architecture spike (kept for reference)

Run a single test file: `pytest tests/test_preprocessor.py -v`

## Editing this file

When you change the release flow, add a new feature flag, or change
something a future Claude session would need to know to avoid
breaking, **update this file in the same PR**. Stale agent guidance
costs more debugging than the cost of writing it down.
