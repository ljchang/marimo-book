# Authoring content

A `marimo-book` is just a directory of files referenced by `book.yml`.
You can author pages as plain Markdown (`.md`), marimo notebooks
(`.py`), or any mix of the two.

## Markdown pages (`.md`)

Standard Markdown with the Material for MkDocs dialect on top. Drop a
file into `content/`, reference it from `book.yml`'s `toc:`, and it
becomes a page.

### Admonitions

```markdown
!!! note
    Notes are blue.

!!! warning "A custom title"
    Warnings are orange.

???+ tip "Collapsible (default open)"
    Uses `pymdownx.details` syntax — collapses when you click.
```

Supported types: `note`, `tip`, `warning`, `danger`, `important`,
`seealso`, `abstract`, `info`, `success`, `question`, `failure`, `bug`,
`example`, `quote`.

### Math

Inline `$x^2$` and block `$$...$$` blocks work. amsmath environments
(`align`, `equation`, etc.) are supported:

```markdown
$$
\begin{align}
\hat{\boldsymbol{\beta}} &= (X^\top X)^{-1} X^\top \mathbf{y}
\end{align}
$$
```

### Code blocks

```markdown
```python
def hello():
    return "world"
```
```

Syntax-highlighted, with a copy button in the top-right corner. Works
for every language Pygments understands.

### Tables

Standard GitHub-flavoured Markdown tables work:

```markdown
| Column | Type | Notes |
|---|---|---|
| a     | int  | ok    |
| b     | str  | ok    |
```

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

## Live example

[The next page](example.md) *is* a real marimo notebook, rendered by
`marimo-book`. Open its source on GitHub (via the button at the top of
that page) to see how it's authored.
