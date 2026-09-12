import marimo

__generated_with = "0.24.1"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _():
    x = [1, 2, 3]
    x
    return


@app.cell
def _():
    d = {"name": "Ada", "n": None, "ok": True, "f": 1.5, "s": {3}, 2: "int key", "nested": {"k": ["a", 1]}}
    d
    return


@app.cell
def _(mo):
    mo.vstack([1 + 2, [1, 2, 3], "my string"])
    return


if __name__ == "__main__":
    app.run()
