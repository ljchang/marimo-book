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
2. Tag merged `main` at that commit and push the tag:

   ```bash
   git checkout main && git pull
   git tag -a v0.1.18 -m "Release 0.1.18"
   git push origin v0.1.18
   ```

   The pushed tag fires `publish.yml` → PyPI. Watch the run:
   `gh run watch --repo ljchang/marimo-book` (or the Actions tab).

That's it. **Never push version edits directly to main**, and never
push a `v*` tag you don't intend to publish — the tag *is* the
release trigger. The version lives in exactly one place: the git tag.

**Note (2026-06): the `release-drafter` GitHub-Release draft is stale**
(stuck at `v0.1.11`) and is **not** part of the live flow — releases
`v0.1.12`–`v0.1.17` were cut by direct tag push and have no GitHub
Release object at all. Don't rely on "publish the draft"; push the tag.
If you want GitHub Release notes too, run
`gh release create v0.1.18 --generate-notes` *instead of* the manual
`git push origin v0.1.18` (creating a release also creates+pushes the
tag, which fires `publish.yml` the same way) — but the tag push is the
only thing that actually publishes to PyPI.

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

## Feature flags users can opt into via `book.yml`

| Flag | Effect | Extra needed |
|---|---|---|
| `social_cards: true` | Material's `social` plugin auto-generates per-page OG/Twitter card PNGs | `marimo-book[social]` (pulls Pillow + cairosvg, ~20 MB; needs system `libcairo2 libpango-1.0-0 libpangocairo-1.0-0`) |
| `cross_references: true` | `mkdocs-autorefs` resolves `[Heading text][]` to whichever page has that heading (MyST `{ref}` analog) | `marimo-book[autorefs]` |
| `check_external_links: true` | `htmlproofer` validates external URLs at build (slow; CI-only) | `marimo-book[linkcheck]` |
| `include_changelog: true` | Preprocessor copies `CHANGELOG.md` from book root (or its parent) into the staged tree and appends a "Changelog" entry to the nav | None |
| `pdf_export: true` | `mkdocs-with-pdf` renders the whole book to `_site/pdf/book.pdf` via WeasyPrint and adds a "Download PDF" link to the footer | `marimo-book[pdf]` (same cairo/pango system deps as `[social]`) |
| `precompute.enabled: true` | Detects discrete `mo.ui.*` widgets, re-exports per value, ships a JSON lookup table embedded in the page; JS shim swaps reactive cells on widget input. Caps in `precompute.{max_values_per_widget, max_combinations_per_page, max_seconds_per_page, max_bytes_per_page}`. Multi-widget independent + joint cross-products both supported (since v0.1.0a6). Auto-no-op on WASM pages. | None |
| `defaults.mode: wasm` (or per-entry `mode: wasm`) | Page rendered via `MarimoIslandGenerator`. Marimo's runtime + Pyodide load in the browser; cells become natively reactive, continuous sliders work, no precompute caps. Heavy first paint (~30 MB Pyodide download, cached after first visit). Per-page opt-in is the recommended pattern — leave most pages static for fast loads, enable wasm only on chapters that need full interactivity. **For these pages the build also AST-injects an `await micropip.install([...])` block into the first `@app.cell`** because the islands JS bundle has no PEP 723 / micropip hook of its own — Pyodide-bundled packages auto-load via `loadPackagesFromImports`, but pure-Python PyPI-only deps (`nltools`) silently fail without the explicit install. Wrapped in `try/except ImportError` so build-time CPython doesn't crash. | None (CDN bundle from jsdelivr by default) |
| `dependencies.auto_pep723: true` | Auto-generate `# /// script` PEP 723 blocks from each notebook's imports for *static + sandbox* pages too (WASM pages always get this regardless of the flag). Build stages a **sibling _file_** copy with the block injected (same directory as the source, so the notebook's `__file__` keeps its directory depth — a sub-tempdir would break `Path(__file__).resolve().parent.parent` root detection on WASM pages); user `.py` files are never modified. **Note**: only the PEP 723 block — the WASM micropip bootstrap is WASM-mode-only. Companion CLI `marimo-book sync-deps` writes blocks back into source for `molab` portability. Other knobs: `dependencies.{pin: env, extras: [...], overrides: {mod: dist}, requires_python: ">=3.11"}`. Module → distribution mapping uses marimo's own ~777-entry table; staged sibling files use prefix `marimo_book_pep723_` (precompute staging uses `marimo_book_precompute_`); both are created via `staged_sibling_file()` and swept by the orphan cleanup if a build is interrupted. | None |
| `blog.enabled: true` | Opt-in blog / news module on Material's `blog` + `tags` plugins (and `rss` when `blog.rss`, default on). Posts (`.md` or marimo `.py`) drop by convention into `<book>/blog/posts/` — **not** listed in the TOC. Metadata via YAML front-matter (`.md`) or a `# /// blog` block (`.py`, mirrors the PEP 723 `# /// script` shape); `date` defaults from a `YYYY-MM-DD-…` filename then git/mtime, `title` from the first H1. Bylines come from a **merged roster**: `book.yml` authors (auto-slugified ids) ∪ an optional `<book>/.authors.yml` (the explicit file wins on collision); an omitted `authors:` falls back to `blog.default_author` or the sole roster entry. Posts render through the normal pipeline (`.py` posts are static in v1) and a teaser `<!-- more -->` is auto-inserted (overridable). `marimo-book new-post "Title"` (`--notebook` for `.py`) scaffolds one. Knobs: `blog.{title, dir, rss, default_author}`. | `marimo-book[blog]` (RSS feed only — the blog/tags plugins ship with `mkdocs-material`) |

All nine are off by default in `marimo-book new` scaffolds.

### Custom domain (CNAME)

Drop a `CNAME` file at the book root (next to `book.yml`) containing
the apex domain (e.g. `marimobook.org`). The preprocessor copies it
into the staged docs tree so mkdocs ships it as `_site/CNAME` —
GitHub Pages then keeps the custom-domain setting on every redeploy.
DNS still has to be configured at the registrar (four `A` records on
the apex pointing at GitHub's Pages IPs, plus a `www` `CNAME` →
`<user>.github.io`). The `marimo-book` self-hosted docs use this
pattern for `marimobook.org` (see `docs/CNAME`).

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
