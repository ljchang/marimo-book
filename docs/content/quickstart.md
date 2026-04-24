# Quickstart

## Install

```bash
pip install marimo-book
```

Requires Python 3.11+. Optional extras:

- `pip install 'marimo-book[linkcheck]'` — adds external-link validation
  via `mkdocs-htmlproofer-plugin`.
- `pip install 'marimo-book[dev]'` — adds `pytest`, `ruff` for working
  on the tool itself.

## Five-minute tour

```bash
# Scaffold a new book
marimo-book new mybook
cd mybook

# Live-reload dev server (http://127.0.0.1:8000/)
marimo-book serve

# One-shot static build (emits ./_site/)
marimo-book build

# Validate book.yml + content without building
marimo-book check

# Remove build artifacts
marimo-book clean
```

## What `marimo-book new` gives you

```
mybook/
├── book.yml                    # TOC, theme, launch buttons
├── content/
│   ├── intro.md                # a hand-authored Markdown page
│   └── example.py              # a marimo notebook
├── .github/workflows/
│   └── deploy.yml              # GitHub Pages deploy on push to main
├── .gitignore
└── README.md
```

Open `book.yml` in an editor, set `title:` and `repo:` to match your
project, and drop your own `.md` / `.py` files into `content/`.
Reference them from the `toc:` section in the order you want them to
appear in the sidebar.

## Authoring loop

1. `marimo-book serve` starts the dev server.
2. Edit any `.md` or `.py` file under `content/`.
3. The file watcher coalesces filesystem events, reruns the
   preprocessor (under ~1 s for a Markdown edit, a few seconds for a
   marimo notebook), and mkdocs' livereload asks the browser to refresh.

!!! tip
    On some macOS setups, mkdocs' browser push reload is flaky. If the
    browser doesn't auto-refresh after a save, hard-refresh (⌘-R). The
    build pipeline itself is reliable; only the browser push is
    affected.

## Deploy

The scaffold includes a ready-to-go GitHub Pages workflow at
`.github/workflows/deploy.yml`. Push to `main`, enable Pages on your
repo (`Settings → Pages → Build from GitHub Actions`), and the workflow
publishes automatically.

See [Publishing → Deploying](deploying.md) for alternatives including
Netlify, Cloudflare Pages, and self-hosting.
