import marimo

__generated_with = "0.23.2"
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Live example: a marimo notebook rendered by marimo-book

    This entire page is authored as a marimo notebook (`docs/content/example.py`)
    and built by `marimo-book`. Everything below is rendered statically —
    no Python kernel is running in your browser. Click the *Open in molab*
    button above to load this page as a live marimo session.

    ## A visible code cell

    The next cell is a plain `@app.cell` (no `hide_code=True`), so you
    see both its source and its output.
    """)
    return


@app.cell
def _():
    import math

    angles = list(range(0, 361, 30))
    cosines = [round(math.cos(math.radians(a)), 3) for a in angles]
    table = list(zip(angles, cosines, strict=True))
    table
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Math cells

    `mo.md` blocks support inline math like $f(x) = \int_{-\infty}^{\infty} \hat f(\xi)\, e^{2\pi i x \xi}\, d\xi$
    and display math rendered by MathJax:

    $$
    \frac{d}{dx}\bigg[\int_a^x f(t)\, dt\bigg] = f(x)
    $$
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.callout(
        mo.md("**Callouts** authored with `mo.callout(..., kind='info')` render as Material admonitions."),
        kind="info",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.callout(
        mo.md("Other kinds work too: `kind='warn'` → warning, `kind='danger'` → danger."),
        kind="warn",
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Hidden setup cells

    The very first cell of every marimo notebook — typically a bunch of
    `import` statements — is hidden by default. You can opt out per-book
    by setting `defaults.hide_first_code_cell: false` in `book.yml`.

    ## What you don't see

    - A Python kernel (there isn't one — cell outputs are baked at build).
    - Marimo's full runtime (we load a tiny shim for anywidgets only).
    - Ads, telemetry, or a CDN for the core theme (all local).
    """)
    return


if __name__ == "__main__":
    app.run()
