import marimo

__generated_with = "0.23.3"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Simple Notebook

    A tiny fixture for the marimo-book preprocessor tests. It has a title,
    one hidden import cell, a markdown cell, a code cell with an output,
    and a callout.
    """)
    return


@app.cell
def _():
    x = 2 + 3
    x
    return


@app.cell(hide_code=True)
def _(mo):
    mo.callout(
        mo.md("This is a callout from `mo.callout`."),
        kind="info",
    )
    return


if __name__ == "__main__":
    app.run()
