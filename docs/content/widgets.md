# Anywidgets

Marimo's [anywidget](https://anywidget.dev) integration lets you author
fully interactive UI components as small ES modules. On a live marimo
notebook these render inside a marimo kernel that mediates Python ↔ JS
state; on a static `marimo-book` page, there's no kernel. `marimo-book`
makes anywidgets render anyway via a small runtime shim that's loaded
on every page.

## How it works

1. During build, `marimo export ipynb` outputs each anywidget as a
   `<marimo-anywidget>` custom element with the widget's ES module
   **inlined as a base64 data URL** on the `data-js-url` attribute.
2. The preprocessor rewraps it as
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

### 1. `widget_defaults` in `book.yml`

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

## Elements we strip

Marimo's `<marimo-ui-element>` wrappers around standalone controls —
`<marimo-slider>`, `<marimo-switch>`, `<marimo-dropdown>`,
`<marimo-radio>`, `<marimo-number>`, `<marimo-button>` — require a
running kernel to be meaningful. `marimo-book` strips them at preprocess
time. For static pages, use an anywidget that includes its controls
inside the widget itself, opt the page into
[`mode: wasm`](building.md#wasm-render-mode), or rely on
[`precompute.enabled`](building.md#static-reactivity) for
discrete-value sliders.

## Example: dartbrains widgets

[Dartbrains](https://github.com/ljchang/dartbrains) ships ten Canvas 2D
and Three.js anywidgets (compass, magnetization, precession, spin
ensemble, k-space, encoding, convolution, transform cube, cost function,
smoothing) that render live on static pages with this pipeline. Its
`book.yml` `widget_defaults` block is a good template to copy.
