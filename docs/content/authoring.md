# Authoring content

A `marimo-book` is just a directory of files referenced by `book.yml`.
You can author pages as plain Markdown (`.md`), marimo notebooks
(`.py`), or any mix of the two.

## Markdown pages (`.md`)

Standard Markdown with the Material for MkDocs dialect on top. Drop a
file into `content/`, reference it from `book.yml`'s `toc:`, and it
becomes a page.

### Admonitions

Source:

```markdown
!!! note
    Notes are blue.

!!! warning "A custom title"
    Warnings are orange.

???+ tip "Collapsible (default open)"
    Uses `pymdownx.details` syntax — collapses when you click.
```

Renders as:

!!! note
    Notes are blue.

!!! warning "A custom title"
    Warnings are orange.

???+ tip "Collapsible (default open)"
    Uses `pymdownx.details` syntax — collapses when you click.

Supported types — each renders with its own icon and color stripe:

!!! note
    `note` — neutral blue, the default for general callouts.

!!! tip
    `tip` — green, for helpful asides.

!!! info
    `info` — cyan, for context the reader needs but isn't critical.

!!! warning
    `warning` — orange, for "watch out" guidance.

!!! danger
    `danger` — red, for breaking changes or destructive operations.

!!! success
    `success` — green checkmark, for confirmation.

!!! question
    `question` — purple, for FAQ-style content.

!!! abstract
    `abstract` — for executive summaries at the top of a long page.

!!! example
    `example` — gold, for worked examples.

!!! quote
    `quote` — for pull quotes from other sources.

Other types: `important`, `seealso`, `failure`, `bug` — same pattern.

### Math

Inline `$x^2$` renders as $x^2$. Block `$$...$$` and amsmath environments
(`align`, `equation`, etc.) are supported:

```markdown
$$
\begin{align}
\hat{\boldsymbol{\beta}} &= (X^\top X)^{-1} X^\top \mathbf{y}
\end{align}
$$
```

Renders as:

$$
\begin{align}
\hat{\boldsymbol{\beta}} &= (X^\top X)^{-1} X^\top \mathbf{y}
\end{align}
$$

### Code blocks

Source:

````markdown
```python
def hello():
    return "world"
```
````

Renders as:

```python
def hello():
    return "world"
```

Syntax-highlighted, with a copy button in the top-right corner. Works
for every language Pygments understands.

### Tables

Standard GitHub-flavoured Markdown tables work.

Source:

```markdown
| Column | Type | Notes |
|---|---|---|
| a     | int  | ok    |
| b     | str  | ok    |
```

Renders as:

| Column | Type | Notes |
|---|---|---|
| a     | int  | ok    |
| b     | str  | ok    |

### Images

Put images under `images/` in your book root. `marimo-book` copies that
directory into the built site. Reference them with relative paths:

```markdown
![alt text](images/diagram.png)
```

If your `.md` lives under `content/` and images are at the repo root
`images/`, the relative path `../images/foo.png` works in source —
`marimo-book` auto-rewrites it to `images/foo.png` in the staged output
so it resolves correctly in the final site.

### Cross-references

`marimo-book` uses Material's standard Markdown — same syntax for cross-refs
inside both `.md` files and `mo.md(...)` cells.

**Page → page.** Reference another file in your TOC by its source path:

```markdown
See [Notebook dependencies](dependencies.md) for the full picture.
```

Renders as: See [Notebook dependencies](dependencies.md) for the full
picture.

**Page → specific heading on another page.** Append the heading slug:

```markdown
Jump to [sandbox mode](dependencies.md#sandbox-mode) directly.
```

Heading slugs are auto-generated from the heading text — lowercased,
spaces become hyphens, punctuation stripped. Renders as: Jump to
[sandbox mode](dependencies.md#sandbox-mode) directly.

**Within-page anchor.** Same syntax, drop the file:

```markdown
[Back to top](#authoring-content).
```

**Resolve by heading text (opt-in).** With `cross_references: true` in
`book.yml`, you can write `[Heading text][]` and it resolves to whatever
page has that heading — the MkDocs equivalent of MyST's `{ref}`. Useful
when you don't want to hard-code paths:

```markdown
The [Anywidgets][] page covers the JS shim in detail.
```

The [Anywidgets][] page covers the JS shim in detail.

No extra install needed — `mkdocs-autorefs` ships with `marimo-book` as of 0.1.5; just opt in per book via `cross_references: true` in `book.yml`.

**Term tooltips.** Define an abbreviation once and it becomes a hover
tooltip everywhere on the page:

```markdown
The *[HTML]* output is bundled inline.

*[HTML]: HyperText Markup Language
```

The *[HTML]* output is bundled inline.

*[HTML]: HyperText Markup Language

**File includes.** Pull a snippet from another file using
`pymdownx.snippets`:

```markdown
--8<-- "snippets/license-blurb.md"
```

Useful for things you need to repeat across pages (license footers,
install snippets, etc.).

## Marimo notebooks (`.py`)

Write notebooks in marimo as you normally would. `marimo-book` invokes
`marimo export ipynb --include-outputs` under the hood, walks the cells,
and converts them into a single Markdown page with:

- **Markdown cells** (`mo.md(...)`) → native page Markdown.
- **Code cells** → fenced `python` blocks with the cell's source. If
  the cell has `hide_code=True`, only its output is rendered.
- **Outputs** → inlined as HTML. Matplotlib plots become `<img>` tags
  with base64 data URIs. Plotly output renders via Plotly.js. `mo.md`
  outputs flatten into Markdown.
- **Callouts** (`mo.callout(..., kind="info")`) → Material
  admonitions. Kinds map:

    | `mo.callout` kind | Material type |
    |---|---|
    | `info` / `note` | `info` |
    | `success` / `tip` | `success` / `tip` |
    | `warn` / `warning` | `warning` |
    | `danger` / `error` | `danger` / `failure` |

- **Anywidgets** (`mo.ui.anywidget(...)`) → live interactive widgets on
  the static page. See [Anywidgets](widgets.md) for the details.

### Setup-cell convention

By default, the first code cell of a marimo notebook is hidden if it
produces no output. This is almost always the `import marimo as mo` +
path-setup cell that users don't care about. Override per-book if you
need the first cell visible:

```yaml
defaults:
  hide_first_code_cell: false
```

### Author lines

Lines of the form `*Written by ...*` in the first Markdown cell are
stripped — `book.yml`'s `authors:` already renders author info on the
page header, and having it twice looks redundant.

### Interactive escape hatch

Every `.py` page gets an "Open in molab" launch button (configurable in
`book.yml`) so readers can pop into a fully reactive marimo session for
any chapter they want to modify.

### Caching slow cells (`mo.persistent_cache`)

For cells that take more than a few seconds to run (large simulations,
ICA decompositions, big bootstraps), wrap the expensive computation in
[`mo.persistent_cache`](https://docs.marimo.io/api/caching/) so the
result lives on disk across builds. The first build pays the cost
once; every subsequent build (including CI, if you commit the cache
directory) is essentially instant.

```python
@app.cell
def _(SimulateGrid, mo):
    with mo.persistent_cache("fpr_sweep"):
        simulation = SimulateGrid(grid_width=100, n_subjects=20)
        simulation.run_multiple_simulations(threshold=0.05, n_simulations=100)
    simulation.plot()  # cheap; runs every build
    return
```

The cache lives at `__marimo__/cache/<cache_name>/` next to the
notebook. Hash invalidation is automatic: edit any input variable in
the cell and the cache for that key is rebuilt on the next run.

If a cell is *so* slow that even the first build is impractical
(massive parameter sweeps, multi-hour fits), fall back to
`@app.cell(disabled=True)` — marimo skips the cell during static
export but it stays runnable in `marimo edit`. Use this sparingly; the
chapter will show no output for that cell.

## Live example

[The next page](example.md) *is* a real marimo notebook, rendered by
`marimo-book`. Open its source on GitHub (via the button at the top of
that page) to see how it's authored.
