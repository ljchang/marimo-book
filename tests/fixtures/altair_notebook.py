import marimo

__generated_with = "0.24.1"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    import altair as alt

    return alt, mo


@app.cell
def _(alt):
    data = alt.Data(values=[{"x": 0, "y": 1.5}, {"x": 1, "y": 0.5}, {"x": 2, "y": 2.0}])
    chart = alt.Chart(data).mark_line(point=True).encode(x="x:Q", y="y:Q")
    chart
    return (chart,)


@app.cell
def _(chart, mo):
    mo.vstack([chart, "caption under the chart"])
    return


if __name__ == "__main__":
    app.run()
