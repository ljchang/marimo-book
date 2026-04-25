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

To cut a release:

1. Open a tiny PR that dates the `[Unreleased]` section in
   `CHANGELOG.md` to today (one-line change). Merge it.
2. Go to <https://github.com/ljchang/marimo-book/releases>. The
   `release-drafter` bot has been maintaining a draft populated with
   bullets from every merged PR. Edit if needed, set the tag (e.g.
   `v0.1.0a3`), and click **Publish release**.
3. The `v*` tag fires `.github/workflows/publish.yml`. `hatch-vcs` reads
   the tag, builds a wheel versioned exactly `0.1.0a3`, ships it to
   PyPI via OIDC Trusted Publisher.

That's it. **Never push version edits directly to main.** The version
lives in exactly one place: the git tag.

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

All five are off by default in `marimo-book new` scaffolds.

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
