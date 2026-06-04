---
title: marimo-book now has a blog
date: 2026-06-04
categories:
  - Announcements
---

marimo-book ships an opt-in **blog / news** module, built on Material for
MkDocs' blog plugin.

<!-- more -->

Turn it on with `blog: {enabled: true}` in `book.yml`, then drop a Markdown
file — or a marimo `.py` notebook — into `blog/posts/`. Posts are
auto-discovered by date; you never touch the table of contents. Run
`marimo-book new-post "My headline"` to scaffold one with the header
pre-filled.

Because a post can be a full marimo notebook, an announcement can embed a
live, interactive demo right in the feed.
