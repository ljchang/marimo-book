import marimo

__generated_with = "0.23.3"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(
        r"""
        # WASM demo

        This page is rendered with `mode: wasm`. Marimo's runtime loads
        in your browser via Pyodide on first paint (one-time download
        ~30 MB; subsequent visits are cached). Once loaded, the slider
        below is **truly reactive** — no precomputed lookup table, no
        caps. Drag continuously and the cell below recomputes Python
        on each input.

        Compare this with the [Static reactivity demo](precompute_demo.md),
        which precomputes a fixed grid of values at build time and
        ships zero Python at runtime. Both approaches have their place:

        - **Static + precompute**: instant first paint, works offline,
          tiny page, but limited to a fixed value grid declared at
          author time. Good default.
        - **WASM**: full Python in the browser, every cell reactive,
          continuous sliders work, no caps. But heavy first paint and
          requires the user's browser to download Pyodide.

        Use `mode: wasm` per-page (in `book.yml`'s `toc` entry) for
        chapters that genuinely need full reactivity. Leave the rest
        static for fast loads.
        """
    )
    return


@app.cell
def _(mo):
    # Continuous slider — no precompute caps in WASM mode!
    n = mo.ui.slider(start=1, stop=100, value=10, label="N")
    n
    return (n,)


@app.cell(hide_code=True)
def _(mo, n):
    # Live computation in the browser — runs every time `n` changes.
    total = sum(range(1, n.value + 1))
    closed_form = n.value * (n.value + 1) // 2
    mo.md(
        f"""
        Sum of 1..{n.value} computed live:

        - Loop: **{total}**
        - Closed form (n·(n+1)/2): **{closed_form}**
        """
    )
    return


if __name__ == "__main__":
    app.run()
