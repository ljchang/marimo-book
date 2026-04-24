# My Marimo Book

Built with [marimo-book](https://github.com/ljchang/marimo-book).

## Local development

```bash
pip install marimo-book

# Live-reload dev server (browse at http://127.0.0.1:8000/)
marimo-book serve

# One-shot build (emits ./_site/)
marimo-book build

# Validate book.yml + content without building
marimo-book check

# Remove build artifacts
marimo-book clean
```

## Layout

- `book.yml` — TOC, theme, branding, launch-button config
- `content/` — your `.md` and marimo `.py` chapters
- `.github/workflows/deploy.yml` — builds and publishes to GitHub Pages
  on every push to `main` (edit or delete as needed)
