# Changelog

All notable changes to `marimo-book` will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

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
