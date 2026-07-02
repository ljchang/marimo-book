import marimo

app = marimo.App()


@app.cell
def _():
    raise ValueError("boom")


if __name__ == "__main__":
    app.run()
