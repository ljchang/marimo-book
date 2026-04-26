import marimo

__generated_with = "0.23.3"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo
    from drawdata import ScatterWidget

    return ScatterWidget, mo


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Anywidget demo: drawdata

    [drawdata](https://github.com/koaning/drawdata) is a small
    [anywidget](https://anywidget.dev) — a self-contained ES module
    that draws onto a `<canvas>`. **Click and drag** in the panel
    below to scribble points; press a number key (`1`–`4`) before
    drawing to switch the active class.

    This page is **static** — there is no Python kernel running.
    The widget renders because `marimo-book` extracts the inlined
    ES module from `marimo export`'s output and mounts it via a
    ~150-line shim (`marimo_book.js`). See [Anywidgets][] for the
    full pipeline.
    """)
    return


@app.cell
def _(ScatterWidget, mo):
    canvas = mo.ui.anywidget(ScatterWidget(height=320))
    canvas
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What you can and can't do statically

    - ✅ The widget **renders** — anywidget's `_esm` trait is inlined
      as a `data:` URL, so no kernel and no CDN are required.
    - ✅ All **client-side interaction** works — drawing, brush
      colours, the canvas itself.
    - ❌ The drawn `data` cannot flow into a downstream Python cell.
      That needs a kernel.

    For genuine Python reactivity (drawn points → live DataFrame →
    live plot) flip the chapter to `mode: wasm` in `book.yml`. See
    the [WASM demo](wasm_demo.md) for what that looks like.
    """)
    return


if __name__ == "__main__":
    app.run()
