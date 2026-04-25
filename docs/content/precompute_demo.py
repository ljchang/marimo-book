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
    # Static reactivity demo

    This page shows the `precompute.enabled: true` feature in action.
    The slider below is a real `mo.ui.slider`, but the page is fully
    static — there is no Python kernel running. The output updates
    because marimo-book pre-rendered the notebook once per slider
    value at build time and embedded the results as a JSON lookup
    table.

    Drag the slider to change the temperature reading.
    """)
    return


@app.cell
def _(mo):
    temperature_c = mo.ui.slider(steps=[-10, 0, 10, 20, 25, 30, 40, 100])
    return (temperature_c,)


@app.cell(hide_code=True)
def _(mo, temperature_c):
    c = temperature_c.value
    f = c * 9 / 5 + 32
    k = c + 273.15
    if c <= 0:
        feel = "freezing"
    elif c < 15:
        feel = "cool"
    elif c < 25:
        feel = "comfortable"
    elif c < 35:
        feel = "warm"
    else:
        feel = "hot"
    mo.md(f"""
    | Scale | Value |
    |---|---|
    | Celsius | **{c} °C** |
    | Fahrenheit | {f:.1f} °F |
    | Kelvin | {k:.2f} K |
    | Subjective | _{feel}_ |
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## How this works

    The author wrote a normal marimo notebook. The slider uses marimo's
    own `steps=[-10, 0, 10, 20, 25, 30, 40, 100]` API to declare a
    discrete value set — no marimo-book imports, no special markup.
    With `precompute.enabled: true` in `book.yml`, the preprocessor:

    1. Found the slider via AST scan (eight discrete values).
    2. Re-ran `marimo export ipynb` once per non-default value.
    3. Diffed the rendered cells across versions to find which output
       changed (just the temperature-table cell).
    4. Embedded a small JSON lookup table in the page.
    5. A small JS shim swaps the table's HTML when you drag the
       slider.

    See [Building → Static reactivity](building.md#static-reactivity)
    for the full feature walkthrough, including the caps that protect
    against runaway builds.
    """)
    return


if __name__ == "__main__":
    app.run()
