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
    # Anywidgets

    Marimo's [anywidget](https://anywidget.dev) integration lets you author
    fully interactive UI components as small ES modules. On a live marimo
    notebook these render inside a marimo kernel that mediates Python ↔ JS
    state; on a static `marimo-book` page, there's no kernel. `marimo-book`
    makes anywidgets render anyway via a small runtime shim that's loaded
    on every page.

    ## Live demo: drawdata

    [drawdata](https://github.com/koaning/drawdata) is a small
    [anywidget](https://anywidget.dev) — a self-contained ES module
    that draws onto a `<canvas>`. **Click and drag** in the panel
    below to scribble points; press a number key (`1`–`4`) before
    drawing to switch the active class.

    This page is **static** — there is no Python kernel running.
    The widget renders because `marimo-book` extracts the inlined
    ES module from `marimo export`'s output and mounts it via a
    ~150-line shim (`marimo_book.js`).
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
    ### What you can and can't do statically

    - ✅ The widget **renders** — anywidget's `_esm` trait is inlined
      as a `data:` URL, so no kernel and no CDN are required.
    - ✅ All **client-side interaction** works — drawing, brush
      colours, the canvas itself.
    - ❌ The drawn `data` cannot flow into a downstream Python cell.
      That needs a kernel.

    For genuine Python reactivity (drawn points → live DataFrame →
    live plot) flip the chapter to `mode: wasm` in `book.yml`. See
    the [WASM demo](wasm_demo.md) for what that looks like.

    ## How it works

    1. During build, the notebook is executed and each anywidget comes
       out as a `<marimo-anywidget>` custom element. The widget's ES
       module isn't on that element any more (marimo ≥ 0.24 sends it to
       the frontend on a kernel notification instead), so marimo-book
       captures it from the session and **inlines it as a base64 data
       URL**.
    2. The preprocessor rewraps the element as
       `<div class="marimo-book-anywidget" data-js-url="...">`.
    3. At page load, a ~150-line JS shim
       (`marimo_book.js`, bundled via `extra_javascript`) finds each mount,
       dynamically imports the module via `import()`, builds a minimal
       anywidget-compatible `model` object, and calls
       `module.default.render({model, el})`.

    No marimo runtime needed. No WebSocket. Just one JS file and the
    widget's own ES module.

    ## Seeding widget state

    Anywidget JS modules typically read initial state via `model.get("key")`.
    Since there's no live kernel to provide that state, `marimo-book` has
    to seed it before `render()` is called.

    Two precedence layers — both optional; whichever values exist at each
    layer are merged (later wins):

    ### 1. widget_defaults in book.yml

    ```yaml
    widget_defaults:
      CompassWidget:
        b0: 3.0
      PrecessionWidget:
        b0: 3.0
        flip_angle: 90.0
        t1: 0.0
        t2: 0.0
        show_relaxation: false
        paused: false
    ```

    One entry per widget *class* name. Recommended when multiple cells
    instantiate the same widget and you want them all to share the same
    defaults.

    ### 2. Literal kwargs in the cell

    ```python
    @app.cell
    def _(mo):
        mo.ui.anywidget(PrecessionWidget(flip_angle=30.0, show_relaxation=True))
        return
    ```

    `marimo-book` walks the cell's AST, finds the widget constructor call
    (any CamelCase class ending in `Widget`, `View`, or `Mount`), and
    extracts literal kwargs (`int`, `float`, `bool`, `str`, `None`, `list`,
    `dict`). These override `widget_defaults` for that specific mount.

    ## Troubleshooting

    **"Nothing renders, but I see a placeholder div in DevTools."**

    - Check the browser console for an import error. A typo in the
      widget's data URL would show as a syntax error.
    - Confirm that `javascripts/marimo_book.js` loaded (Network tab).

    **"The widget renders but throws `Cannot read properties of undefined`
    in an animation loop."**

    - The widget's JS is reading a `model.get("key")` that isn't seeded.
      Either add that key to `widget_defaults` in `book.yml`, or make the
      widget JS defensive with `model.get("key") ?? defaultValue`.

    **"I want the widget to persist state between page navigations."**

    - State lives in the mount `<div>`; Material's instant navigation
      re-runs the shim on every page load. For state that needs to
      persist, store it in `localStorage` from inside your widget's JS.

    ## Plotly figures

    Plotly figures (anything that produces a `plotly.graph_objects.Figure`,
    including `make_subplots`, `px.scatter`, etc.) render fully interactive
    on static pages — zoom, pan, hover, the whole toolbar.

    The pipeline:

    1. Marimo's exporter emits each figure as
       `<marimo-plotly data-figure='{json}' data-config='{json}'>` with the
       complete figure spec inlined.
    2. The preprocessor rewraps it as
       `<div class="marimo-book-plotly" data-figure='{json}'>`.
    3. On page load, `marimo_book.js` lazy-loads Plotly.js from jsdelivr
       (cached after first chapter that has a chart) and calls
       `Plotly.newPlot(mount, data, layout, config)` per mount.

    No kernel, no extra setup. Just write the figure as you would in any
    marimo notebook and it renders as the static last expression of its
    cell.

    ```python
    @app.cell(hide_code=True)
    def _(go, x, y):
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=x, y=y, mode='lines'))
        fig.update_layout(title="My chart", height=400)
        fig
        return
    ```

    CSS reserves a 320 px slot before hydration so the page doesn't jump
    when Plotly mounts. If your chart needs more space, set
    `fig.update_layout(height=...)` — the Plotly height wins.

    ## Altair charts

    Altair charts render the same way. marimo formats a chart as a
    Vega-Lite spec (`application/vnd.vegalite.v*+json`, or a
    `<marimo-mime-renderer>` element when the chart sits inside `mo.vstack`
    and friends); the preprocessor emits
    `<div class="marimo-book-vega" data-spec='{json}'>` and `marimo_book.js`
    lazy-loads vega, vega-lite and vega-embed from jsdelivr on the first
    page that has one. Tooltips, selections and the rest of Vega-Lite's
    interactivity work; the chart re-embeds when the reader toggles
    light/dark mode. Embed options set via
    `alt.renderers.set_embed_options(...)` are honoured.
    """)
    return


@app.cell
def _():
    import altair as alt

    _data = alt.Data(values=[{"x": i, "y": ((i * 7) % 11) / 10} for i in range(12)])
    alt.Chart(_data).mark_line(point=True).encode(
        x="x:Q", y="y:Q", tooltip=["x:Q", "y:Q"]
    ).properties(width="container", height=240, title="Altair on a static page")
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Lists and dicts

    A bare `list`, `tuple` or `dict` as a cell's last expression is not HTML
    either — marimo ships it as JSON (with markers for floats, sets, tuples
    and non-string keys) and draws a tree in its frontend. The preprocessor
    renders that tree statically: one row per item, bare keys, Python
    literals for leaves, coloured with the theme's code-highlight tokens.
    The same happens for a structure nested in `mo.vstack` & co.
    """)
    return


@app.cell
def _():
    {"name": "Ada", "scores": [9.5, 8.0], "tags": {"math", "logic"}, 2: "int key"}
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Elements we strip

    Marimo's `<marimo-ui-element>` wrappers around standalone controls —
    `<marimo-slider>`, `<marimo-switch>`, `<marimo-dropdown>`,
    `<marimo-radio>`, `<marimo-number>`, `<marimo-button>` — require a
    running kernel to be meaningful. `marimo-book` strips them at
    preprocess time. For static pages, use an anywidget that includes its
    controls inside the widget itself, opt the page into
    [`mode: wasm`](building.md#wasm-render-mode), or rely on
    [`precompute.enabled`](building.md#static-reactivity) for
    discrete-value sliders.

    ## Example: dartbrains widgets

    [Dartbrains](https://github.com/ljchang/dartbrains) ships ten Canvas 2D
    and Three.js anywidgets (compass, magnetization, precession, spin
    ensemble, k-space, encoding, convolution, transform cube, cost function,
    smoothing) that render live on static pages with this pipeline. Its
    `book.yml` `widget_defaults` block is a good template to copy.
    """)
    return


if __name__ == "__main__":
    app.run()
