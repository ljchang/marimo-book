# Cached notebook outputs (`mode: cached`)

Some notebooks are too expensive to run on every docs deploy — they load GPU
models, hit the network, or take minutes to execute. `mode: cached` lets you
**run them once, commit the rendered output, and let CI build the site without
executing anything.** It's the marimo-book analogue of Jupyter Book's
`execute: off`.

## How it works

1. You mark a notebook `mode: cached`.
2. On *your* machine (with the real dependencies) you run `marimo-book render`.
   That executes the cached notebooks and commits their rendered bodies under a
   version-controlled `_rendered/` directory.
3. You commit `_rendered/` alongside your notebooks.
4. CI (or anyone) runs `marimo-book build` — the cached pages come straight from
   `_rendered/`, **no execution, no dependencies, no GPU required.**

Only the notebook *body* is stored (not launch buttons or link rewrites), so
changing `launch_buttons`, your repo URL, or the table of contents never forces
a re-render — only editing the notebook (or its render-affecting config) does.

## Enable it

Per page, or as the book-wide default:

```yaml
# book.yml
toc:
  - file: chapters/train_model.py
    mode: cached          # this heavy notebook only

# …or default everything to cached:
defaults:
  mode: cached
```

No extra to install — `mode: cached` is built in.

## The author workflow

```bash
# Run the cached notebooks once, with their real deps, and commit the output:
marimo-book render
git add _rendered/
git commit -m "Re-render cached notebooks"
```

Then a plain build never executes them:

```bash
marimo-book build        # cached pages served from _rendered/
```

If you edit a cached notebook, re-run `marimo-book render` and commit the
updated `_rendered/` — otherwise the committed output is stale.

## Keeping CI honest

A committed body is considered **fresh** only when the notebook source *and* the
render-affecting config (`defaults`, `dependencies`, `widget_defaults`) *and* the
marimo-book version all match what was rendered. Change any of them and the
artifact is correctly treated as stale.

Two tools enforce freshness so a stale page never sneaks through:

- **`marimo-book render --check`** executes nothing and exits non-zero if any
  cached page is out of date — drop it into CI as a gate:

  ```yaml
  - run: marimo-book render -b docs/book.yml --check
  ```

- **`marimo-book build --strict`** turns a stale or missing cached artifact into
  a hard build error (instead of silently re-executing it). Use `--strict` for
  release/CI builds so a forgotten `render` fails loudly.

During an ordinary local `marimo-book build` (no `--strict`), a stale page just
warns and falls back to a live render, so day-to-day authoring still works even
before you've re-rendered.

## Trade-offs

- `_rendered/` is committed to your repo, and the bodies embed cell outputs
  (images/HTML as base64) — the same repo-size trade-off as committing Jupyter
  notebook outputs. Worth it when the alternative is a multi-minute or
  GPU-bound build on every deploy.
- For notebooks that are cheap to run, leave them on the default `static` mode
  (executed at build, nothing committed).
- For full in-browser interactivity instead of static output, see `mode: wasm`.
