# /// script
# requires-python = ">=3.11"
# dependencies = ["marimo"]
# ///

import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
        # Assignment: Compound interest

        A tiny stand-in for a grader-published student notebook, so this book can
        show the assignment drawer with something real in it. A published
        assignment carries its grader identity in the PEP 723 block at the top of
        the file, and its sign-in, check and submit cells come from the grader's
        widget; this one only has questions and their checks.

        Answer in the cells marked `# YOUR CODE HERE`. Your work is saved in this
        browser as you type — open **History** in the drawer's bar to see every
        version of it, and to restore one.
        """
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
        ## Q1. Sum of the first n squares

        Set `squares` to the sum of the squares of 1..10.
        """
    )
    return


@app.cell
def _():
    squares = ...
    # YOUR CODE HERE
    return (squares,)


@app.cell(hide_code=True)
def _(mo, squares):
    mo.stop(squares is ..., mo.md("_Fill in `squares` above; this check runs once it is defined._"))
    mo.md("✅ Correct." if squares == 385 else "❌ Not yet — expected 385.")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
        ## Q2. A reactive slider

        Make `doubled` twice the slider's value. Drag the slider to see the check
        re-run.
        """
    )
    return


@app.cell
def _(mo):
    k = mo.ui.slider(1, 20, value=7, label="k")
    k
    return (k,)


@app.cell
def _(k):
    doubled = ...
    # YOUR CODE HERE
    _ = k.value
    return (doubled,)


@app.cell(hide_code=True)
def _(doubled, k, mo):
    mo.stop(doubled is ..., mo.md("_Fill in `doubled` above._"))
    mo.md("✅ Correct." if doubled == 2 * k.value else f"❌ Not yet — expected {2 * k.value}.")
    return


if __name__ == "__main__":
    app.run()
