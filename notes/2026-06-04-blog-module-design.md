# Blog / News module — design spec

- **Date:** 2026-06-04
- **Status:** Approved (brainstorm complete) — pending implementation plan
- **Owner:** ljchang
- **Feature flag:** `blog:` in `book.yml` (off by default)

## 1. Summary

Add an opt-in **blog / news / announcements** module to marimo-book, built on
**Material for MkDocs' built-in `blog` plugin** (free and MIT since mkdocs-material
v9.7.0, 2025-11-11) plus **`mkdocs-rss-plugin`** for feeds. Posts are authored by
convention (drop a file in `blog/posts/`), can be **either markdown `.md` or marimo
`.py` notebooks**, and flow through marimo-book's existing render/export pipeline so a
post can embed live interactive cells.

The design deliberately keeps every artifact the plugin consumes in **standard
Material shape** (`blog` plugin config, `.authors.yml`, post front-matter, RSS plugin),
so the eventual port to **zensical** is "drop the marimo-book glue, keep the outputs."

## 2. Goals / non-goals

### Goals
- News-first defaults (dated posts + reverse-chron index + RSS), with the plugin's
  richer features (categories, tags, author profiles, drafts, archive) available but
  not required.
- Authoring by convention — no `book.yml` TOC edit per post.
- Posts may be `.md` or marimo `.py` (static or wasm), reusing the existing pipeline.
- Ergonomic metadata: a single "post header" model with smart defaults; almost every
  field optional.
- Author roster that scales from a solo maintainer to a large contributor community
  without bloating `book.yml` (**support both** sources).
- Maximum portability to zensical.

### Non-goals (v1)
- Comments.
- Custom per-post layouts/templates beyond what the plugin offers.
- Multiple independent blogs / blog sections.
- Blog-specific search tuning beyond the default search plugin.
All remain reachable later via the plugin if needed.

## 3. Decisions (from brainstorm)

| # | Decision |
|---|---|
| Post format | **Both** `.md` and marimo `.py` (static or wasm). |
| Discovery | **Convention** — auto-discover `<book_root>/blog/posts/**`; no per-post TOC entry. |
| Feature scope | **News-first**, full plugin features available (categories/tags/authors/archive/drafts) but off-emphasis. |
| Header | YAML front-matter for `.md`; a `# /// blog` block for `.py` (mirrors PEP 723 `# /// script`), lifted into the staged `.md`'s front-matter. |
| Authors | **Support both**: a merged roster of `book.yml` authors (auto-derived) ∪ optional `.authors.yml` (authoritative on id collision). |
| Default author | `blog.default_author` if set; else the sole roster entry; else no byline. |
| Teaser (`.py`) | **Auto-insert** the excerpt cut after the first rendered markdown cell; author can override with an explicit marker. |
| Scaffold | **In scope for v1**: `marimo-book new-post "Title"` (`--notebook` for `.py`). |
| Config home | `book.yml` (same file as `toc:`; there is no separate TOC file). |
| Feed | RSS on by default when `blog.enabled`, via `mkdocs-rss-plugin` (new `[blog]` extra). |

## 4. Content model

- A **post** is a `.md` file or a marimo `.py` notebook placed in
  `<book_root>/blog/posts/` (folder name = `blog.dir`, default `blog`; posts live in
  its `posts/` subfolder, matching Material's `blog_dir`/`post_dir` convention).
- Posts are **auto-discovered** and ordered by `date`. They are NOT listed in `book.yml`'s
  `toc:`.
- Each post is rendered through marimo-book's existing page pipeline:
  - `.md` → standard markdown transforms.
  - `.py` → `marimo export` (+ precompute / wasm islands per the post's mode), exactly as
    a normal notebook page, producing a rendered `.md` with inlined outputs.
- The rendered post `.md` is staged under `_site_src/docs/<blog.dir>/posts/` with the
  correct front-matter, where the Material `blog` plugin picks it up.

## 5. Authoring header

### 5.1 Markdown posts
Standard YAML front-matter the plugin reads natively:
```markdown
---
title: marimo-book 0.2 released     # optional — falls back to first "# H1"
date: 2026-06-04                    # see defaults below
authors: [luke]                     # optional — ids into the merged roster
categories: [Announcements]         # optional
tags: [release, wasm]               # optional
draft: true                         # optional
pin: true                           # optional
---

Teaser shown on the index.
<!-- more -->
Full body.
```

### 5.2 marimo `.py` notebook posts
A marimo `.py` file can't lead with `---` front-matter, so metadata lives in a
**`# /// blog` block** (same shape as the `# /// script` PEP 723 block marimo-book already
parses). The preprocessor parses it and **emits the equivalent YAML front-matter onto the
staged `.md`**, then the block is irrelevant to the notebook's execution.
```python
# /// blog
# title = "marimo-book 0.2 released"
# date = 2026-06-04
# authors = ["luke"]
# tags = ["release"]
# ///
import marimo
app = marimo.App()
...
```
- Field names mirror the front-matter keys (`title`, `date`, `authors`, `categories`,
  `tags`, `draft`, `pin`).
- Coexists with `# /// script` (PEP 723) if present; the two blocks are independent.

### 5.3 Smart defaults (almost everything optional)
| Field | If omitted |
|---|---|
| `date` | derive from a `YYYY-MM-DD-…` filename prefix; else git first-commit date; else file mtime. marimo-book **guarantees** a date so the plugin never errors. |
| `authors` | resolve via the default-author rule (§6). |
| `title` | first `# H1` (`.md`) / first markdown cell heading (`.py`). |
| `categories`, `tags` | omitted (fully optional). |

A minimal news post = a dated filename + a body.

## 6. Author model (support both)

The effective byline roster is a **merge**:

```
roster = derive_from_book_yml_authors(book.authors)  ∪  parse(.authors.yml if present)
```

- **`book.yml` authors → auto-derived entries.** Each `Author` (name/orcid/affiliation/
  email) becomes a roster entry with a **slugified id** (e.g. `Luke Chang` → `luke-chang`),
  `name` from `name`, `description` from affiliation/ORCID, `avatar`/`url` derived where
  possible (e.g. GitHub avatar). Solo/small books need **no new file**.
- **`<book_root>/.authors.yml` (optional)** — standard Material schema
  (`id → {name, description, avatar, url}`). Merged on top of the derived entries;
  **wins on id collision** (the explicit file is authoritative). This is where a growing
  contributor community lives.
- The preprocessor writes the **merged** `.authors.yml` into the staged blog dir — which
  is byte-for-byte the file zensical will consume.

### Default-author resolution (post omits `authors:`)
1. `blog.default_author` (an id) if set; else
2. the sole roster entry if the roster has exactly one author; else
3. no byline.

`book.yml`'s existing `authors:` (the book's academic title-page byline) is **left
untouched** — separate concern, no forced coupling.

## 7. Config surface (`book.yml`)

A `blog:` block matching the existing `precompute:` / `dependencies:` object pattern;
off by default.

```yaml
blog:
  enabled: true          # default false
  title: News            # nav label; default "Blog"
  dir: blog              # source folder under book root; default "blog"
  rss: true              # emit an RSS feed; default true when enabled
  default_author: luke   # optional id; see §6
```

Pydantic model `Blog` (in `config.py`), added as `Book.blog: Blog = Blog()`. Mirrors the
`Precompute`/`Dependencies` style (object with defaults, `enabled: bool = False`).
Richer plugin options (categories_allowed, pagination, archive format, …) are NOT
surfaced in v1 — they flow through post front-matter or can be added to the model later.

## 8. Pipeline integration

### 8.1 Preprocessor (`preprocessor.py`)
New step, gated on `book.blog.enabled`:
1. **Discover** `<book_root>/<blog.dir>/posts/**` (`.md` + `.py`).
2. For each post: parse the header (front-matter or `# /// blog`), apply defaults
   (§5.3), render through the existing page renderer (`.py` → export/precompute/wasm as
   usual), and **stage** the rendered `.md` to `_site_src/docs/<blog.dir>/posts/` with
   the resolved front-matter prepended.
3. **Teaser:** for `.py` posts (and `.md` posts lacking an explicit marker), insert the
   excerpt boundary (`<!-- more -->`) after the first rendered markdown cell/paragraph
   (§9).
4. Write `_site_src/docs/<blog.dir>/index.md` (the plugin's required landing page).
5. Build the **merged `.authors.yml`** (§6) and stage it into the blog dir.

### 8.2 Shell (`shell.py`, `emit_mkdocs_yml`)
When `book.blog.enabled`, extend the generated `mkdocs.yml`:
- Append `"blog"` to `plugins` (config: `blog_dir`/`post_dir`, `post_excerpt: optional`,
  `authors_file`), and—if `blog.rss`—append
  `{"rss": {"use_material_blog": True, "match_path": "<blog.dir>/posts/.*"}}` after `blog`.
- Append `"tags"` to `plugins` (free; enables `tags:` front-matter) whenever the blog is
  enabled (a refinement to make this conditional on any post actually using tags is noted
  in §16 but not required for v1).
- Add a nav entry `{<blog.title>: <blog.dir>/index.md}` (placement: end of nav by
  default).

Plugin order in the generated list: `search` … `blog`, `tags`, `rss` (rss must follow
blog; tags before rss).

## 9. Teaser / excerpt handling

- Material `blog` plugin `post_excerpt: optional`: a post with a `<!-- more -->`
  separator shows the text above it as the index teaser; without one it shows
  metadata only.
- marimo-book guarantees a sensible teaser:
  - `.md` post with an author-placed `<!-- more -->` → respected as-is.
  - `.md` post without one → insert after the first paragraph.
  - `.py` post → insert after the first rendered markdown cell.
  - Override: an explicit marker (a `<!-- more -->` in an `mo.md` cell for `.py`, or in
    the markdown) suppresses the auto-insert.

## 10. Feed (RSS)

- `mkdocs-rss-plugin` added as a new **optional extra**: `marimo-book[blog]`
  (pure-Python, no system deps).
- Wired only when `blog.enabled and blog.rss`, via `use_material_blog: true` +
  `match_path: <blog.dir>/posts/.*`. Emits RSS 2.0 (+ JSON Feed). Dates from git +
  front-matter.
- CI (`ci.yml`) and docs (`docs.yml`) workflows must install the `[blog]` extra if the
  self-hosted docs enable the blog.

## 11. Scaffold command

`marimo-book new-post "Title" [--notebook] [--date YYYY-MM-DD] [--author id]`:
- Writes `<book_root>/<blog.dir>/posts/<date>-<slug>.md` (or `.py` with `--notebook`).
- Pre-fills the header (front-matter or `# /// blog` block) with date (default: today),
  a `title`, and the resolved default author.
- `.py` stub includes a minimal marimo app skeleton + a leading `mo.md` cell for the
  intro/teaser.
- Errors clearly if the blog isn't enabled / `posts/` dir can't be located.

## 12. Dependencies

- `pyproject.toml`: bump `mkdocs-material>=9.7.0` (free blog plugin, pinned posts,
  author profiles) in the base deps. Add `[blog]` optional extra → `mkdocs-rss-plugin`.
- Update `.github/workflows/ci.yml` and `docs.yml` to install `[blog]` where needed.

## 13. zensical portability

Marimo-book-specific glue is confined to the preprocessor and produces standard outputs:
- `.py` `# /// blog` → front-matter lifting (glue; drop at port time — zensical posts are
  `.md`, or zensical may grow its own notebook story).
- `book.yml`-author → roster merge (glue; drop at port time).
Everything the plugin consumes (`blog` config, merged `.authors.yml`, post front-matter,
RSS) is standard Material/zensical shape and ports verbatim. Track zensical's blog-plugin
parity (see the zensical watch-list in `notes/`).

## 14. CLAUDE.md

Add a `blog:` row to the feature-flag table (effect, extra needed `marimo-book[blog]`),
and note: posts live in `blog/posts/`, `.md` or `.py`, header via front-matter / `# ///
blog`, authors via merged `book.yml` + `.authors.yml`. Mention `marimo-book new-post`.

## 15. Testing strategy

- `test_config.py` — `Blog` model defaults + round-trip.
- `test_blog.py` (new) — header parsing (`.md` front-matter, `.py` `# /// blog`), default
  resolution (date from filename/git/mtime, title from H1, author rules), teaser
  insertion (md/py, explicit-marker override), `.authors.yml` merge + id-collision
  precedence, and `book.yml`-author derivation/slugging.
- `test_preprocessor.py` — end-to-end: a `blog.enabled` book with one `.md` and one `.py`
  post stages `blog/index.md`, `blog/posts/*.md` with correct front-matter, and a merged
  `.authors.yml`; non-blog books are unaffected.
- `test_cli_commands.py` — `new-post` writes the expected stub (md + `--notebook`).
- `shell` test — generated `mkdocs.yml` contains `blog` (+ `rss`, `tags`) and the nav
  entry only when enabled, in the correct plugin order.

## 16. Open items deferred to the plan

- Exact slugify rule for `book.yml`-author ids and avatar/url derivation heuristics.
- Whether `tags` plugin is always-on with blog or conditional.
- Nav placement knob (end vs configurable position) — default end for v1.
