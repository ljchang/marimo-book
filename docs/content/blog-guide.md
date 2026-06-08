# Blog / news module

`marimo-book` has an opt-in **blog** built on
[Material for MkDocs' blog plugin](https://squidfunk.github.io/mkdocs-material/plugins/blog/).
Posts can be plain Markdown **or** full marimo notebooks, so an announcement can
embed a live, interactive demo right in the feed.

## Enable it

The blog and tags plugins ship with Material, so the base feature needs no
extra. Install `marimo-book[blog]` only if you want the **RSS feed** (on by
default):

```bash
pip install 'marimo-book[blog]'
```

```yaml
# book.yml
blog:
  enabled: true
  title: News        # nav label (default: "Blog")
```

That's it — a "News" section appears in your nav. You never add posts to the
`toc:`; they're auto-discovered.

## Write a post

Drop a file into `<book>/blog/posts/` — a Markdown `.md` or a marimo `.py`
notebook. Name it `YYYY-MM-DD-slug` so the date is picked up from the filename
(falling back to git history, then the file's mtime):

```
my-book/
├── book.yml
└── blog/
    └── posts/
        ├── 2026-06-04-launch.md
        └── 2026-06-07-interactive-demo.py
```

Or scaffold one with the header pre-filled:

```bash
marimo-book new-post "My headline"            # → blog/posts/<today>-my-headline.md
marimo-book new-post "Live demo" --notebook   # → a marimo .py post
```

### Markdown posts

Metadata goes in YAML front-matter; only the body is required (the title falls
back to the first `# H1`, the date to the filename):

```markdown
---
title: marimo-book now has a blog
date: 2026-06-04
authors: [luke-chang]      # roster ids — see "Authors" below
categories: [Announcements]
tags: [release]
draft: false               # true hides the post from the build
pin: false                 # true keeps it at the top of the list
---

A short teaser paragraph that shows up on the index.

<!-- more -->

The rest of the post, shown only on the post's own page.
```

### Notebook posts

A marimo `.py` post declares its metadata in a `# /// blog` block at the top —
the same shape as a PEP 723 `# /// script` block:

```python
# /// blog
# title = "An interactive release note"
# date = "2026-06-07"
# authors = ["luke-chang"]
# categories = ["Announcements"]
# ///

import marimo as mo
# ... cells render into the post body ...
```

Notebook posts render **statically** in v1 (their outputs are baked in at
build time); set a page to `mode: wasm` elsewhere in the book if you need full
in-browser interactivity.

## The teaser

The text above a `<!-- more -->` marker becomes the excerpt on the index page.
If you don't add one, marimo-book inserts it automatically after the first
paragraph (keeping a leading heading in the teaser). Place your own `<!-- more -->`
to control exactly where the cut falls.

## Authors

Bylines come from a **merged roster**:

1. The `authors:` in your `book.yml` — each gets an auto-slugified id
   (`Luke Chang` → `luke-chang`).
2. An optional `<book>/.authors.yml` (Material's format) — wins on id collision
   and lets you set avatars/descriptions explicitly.

```yaml
# .authors.yml
authors:
  luke-chang:
    name: Luke Chang
    description: Maintainer
    avatar: https://github.com/ljchang.png
```

A post references authors by **id**: `authors: [luke-chang]`. If a post omits
`authors:`, marimo-book uses `blog.default_author` (a roster id) or, when there
is exactly one author in the roster, that author.

## RSS feed

When `blog.rss` is on (the default) and `marimo-book[blog]` is installed, a feed
is generated at `/feed_rss_created.xml`. Item dates come from each post's `date`,
so set `url:` in your `book.yml` for fully-qualified links in the feed.

## All the knobs

```yaml
blog:
  enabled: true
  title: News              # nav label (default: "Blog")
  dir: blog                # source folder under the book root (default: "blog")
  rss: true                # emit an RSS feed (needs the [blog] extra)
  default_author: luke-chang   # roster id used when a post omits authors:
```

!!! note "Heads up: the tags plugin is site-wide"
    Enabling the blog also activates Material's `tags` plugin, which validates
    `tags:` front-matter on **every** page. Keep any `tags:` you put on
    non-blog content pages well-formed (a YAML list) or that page will fail
    the build.
