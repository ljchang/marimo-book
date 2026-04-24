import marimo

__generated_with = "0.23.2"
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
        # Example Notebook

        This notebook demonstrates a few things `marimo-book` handles for you:

        - Hidden setup cells (the `import marimo as mo` above) don't appear
          in the rendered page.
        - `mo.md(...)` cells become native Markdown.
        - Code cells are shown with syntax highlighting and a copy button.
        - Cell outputs are baked in at build time — this page works without
          a Python kernel.
        - `mo.callout(...)` becomes a themed admonition.
        """
    )
    return


@app.cell
def _():
    # Regular code cells run at build time; their output is embedded in the page.
    import math

    values = [math.sin(x / 10) for x in range(10)]
    values
    return (values,)


@app.cell(hide_code=True)
def _(mo):
    mo.callout(
        mo.md("**Hot reload works.** Try editing this cell while `marimo-book serve` is running."),
        kind="info",
    )
    return


if __name__ == "__main__":
    app.run()
