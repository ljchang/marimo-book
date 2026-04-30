# Feedback on `MarimoIslandGenerator` from building marimo-book

**Status:** working draft. Intended as the basis for an eventual upstream
discussion / issue on the marimo repo. Code-line references are pinned to
`marimo-book` at the time of writing — useful for the marimo team to read
alongside our actual workarounds rather than paraphrased ones.

## TL;DR

`MarimoIslandGenerator` is a great runtime-first API: feed it a notebook,
get back HTML that boots Pyodide and re-executes cells reactively in the
browser. We used it to build [marimo-book](https://github.com/ljchang/marimo-book),
which publishes long-form, mostly-static Jupyter-Book-2-shaped sites where
*some* pages need full reactivity and *most* pages just need scrollable
output with maybe a slider that swaps a baked image. The runtime-first
shape of `MarimoIslandGenerator` makes the second case (the common one)
genuinely hard, and we accumulated ~4700 LOC of Python + JS workarounds
for friction that lives almost entirely at the boundary between marimo's
runtime model and a build-time-first publishing pipeline.

We're filing this in the spirit of "here are our scars, here's what would
turn each scar into a one-liner." None of this is a complaint about the
existing API — it's an axis we're pretty sure marimo simply hasn't been
asked to handle yet.

## What we built

`marimo-book` runs as an MkDocs preprocessor:

1. Walks `book.yml` for entries → resolves each to a `.py` notebook.
2. Per entry, picks a render mode: `static` (no kernel; cell outputs baked
   in), `precompute` (static + a build-time lookup table the JS shim
   uses to make sliders swap baked HTML), or `wasm` (full islands runtime,
   live Pyodide kernel).
3. Stages the source with an auto-generated PEP 723 inline-metadata block.
4. For `wasm` entries, calls `MarimoIslandGenerator.from_file(staged).build()`
   and splices the head + body into the staged Markdown.
5. Post-processes the rendered HTML (rewrap anywidgets, strip standalone
   controls in non-wasm modes, inject driver maps), then hands it to
   MkDocs Material for the rest of the pipeline.
6. Ships a runtime shim `marimo_book.js` that hydrates the static
   anywidget mounts, drives precompute swaps, intercepts runtime-emitted
   `<marimo-anywidget>` to bypass the islands trust check, and bridges
   live UIElement values into static-shim widget models.

Step 5 alone is the bulk of `transforms/anywidgets.py` (700 LOC), and
step 6 is `assets/marimo_book.js` (715 LOC). Step 2's `precompute` path is
another 1143 LOC in `transforms/precompute.py`. Almost every line of
those three files exists because there isn't a build-time-first surface
on `MarimoIslandGenerator`.

## Five themes that account for ~80% of the friction

### 1. Anywidgets vs. the runtime trust boundary

**Symptom.** `MarimoIslandGenerator.build()` runs under
`ScriptRuntimeContext`, which hardcodes `virtual_files_supported=False`.
That makes every anywidget's ES module land in the rendered HTML as a
`data:text/javascript;base64,...` URL on `data-js-url`. Then the islands
runtime's `WidgetDefRegistry.getModule` runs an `isTrustedVirtualFileUrl`
check that rejects every `data:` URL emitted before the kernel has set
its `initialized` flag — there is a race on the first batch of widget
cells, and the result is

> Refusing to load anywidget module from untrusted URL: data:...

with the cell's output area left empty.

**What we did.** Two layers:

- **Build-time:** post-process the islands body with
  `rewrite_anywidget_html` (`transforms/anywidgets.py`) to convert every
  `<marimo-anywidget>` into our own `<div class="marimo-book-anywidget">`
  carrying the same data-attrs.
- **Runtime:** install a `MutationObserver` on `document.body` that
  watches for any `<marimo-anywidget>` the kernel later emits during
  cell re-execution, copies its data-attrs onto a fresh
  `<div class="marimo-book-anywidget">`, and replaces the original — then
  loads the module via host-page `import()`, which has no trust check
  (`marimo_book.js:286–313`).

This is the single biggest hack in the codebase. We are essentially
running a parallel renderer for anywidgets to escape a runtime trust
check that doesn't apply to us.

**What would help upstream.** Any of:

- Trust anywidget modules emitted by the same kernel that emitted the
  cell — the URL is build-time-stable and self-issued.
- Expose a `virtual_files_supported=True` toggle on
  `MarimoIslandGenerator.build()` so authors can opt into "I trust my
  own export."
- Emit anywidget modules as static `@file/...` references the runtime
  already trusts, instead of inline `data:` URLs.

### 2. No binding metadata between UIElements and anywidget traits

**Symptom.** The kernel knows that cell A's `slider.value` flows into
cell B's `WidgetClass(b0=slider.value)` — that's the dependency graph
reactivity is built on. None of that binding survives into the rendered
HTML. The static shim therefore has no way to wire a slider drag to a
widget's animation loop.

**What we did.** A second AST pass against the notebook source
(`transforms/anywidgets.py:349–523`):

1. Find every `var = mo.ui.<control>(label=…, start=…, stop=…, step=…)`
   call. Build a tuple signature `(control_tag, label, start, stop, step)`.
2. Find every `WidgetClass(trait=var.value, ...)`. Resolve aliases for
   the common dartbrains pattern `_local = some_slider.value` followed
   by `WidgetClass(trait=_local)`. Resolve `float(var.value)`,
   `int(var.value)`, etc.
3. Walk the rendered HTML for `<marimo-ui-element>` containers, extract
   the inner control's signature from its `data-*` attrs, build a
   `signature → object-id` index.
4. For each anywidget mount (in DOM order), zip-paired to widget
   constructions (in AST order), emit
   `data-driven-by='{trait: object-id, ...}'` in three places: the mount
   itself, its `<marimo-ui-element>` parent, and a page-global
   `<script class="marimo-book-anywidget-drivers">` registry keyed by
   object-id (the only thing that survives WASM mode's full
   island-content swap on first kernel render).

**Pain points along the way.**

- Two cells in dartbrains had `mo.ui.slider(label="Translate X")` for
  unrelated widgets (`CostFunctionWidget` and `TransformCubeWidget`).
  Label-keyed matching gave one widget the other's slider. We had to
  switch to the tuple signature.
- The alias map (`_local = slider.value`) handles a coding pattern that
  seems load-bearing in our notebooks but isn't documented anywhere.
- Empty driver dicts must be preserved in the per-widget list to keep
  the zip-with-DOM-mounts in lock-step. A widget with only literal
  kwargs still occupies a DOM slot; dropping it from the list shifts
  every subsequent mapping by one (this was a real bug we shipped and
  reverted).

**What would help upstream.** A public method on
`MarimoIslandGenerator`, called after `await build()`, returning the
binding map directly:

```python
gen = MarimoIslandGenerator.from_file("nb.py")
await gen.build()
bindings = gen.binding_map()
# {("CostFunctionWidget", "trans_x"): "SFPL-0",
#  ("TransformCubeWidget", "trans_x"): "SFPL-3", ...}
```

The kernel already builds this — it has to, in order to reactively
re-execute downstream cells. Surfacing it as part of the public surface
would collapse 200 LOC of AST walking + matching in marimo-book to a
single dict lookup.

### 3. PEP 723 doesn't reach the runtime

**Symptom.** The islands JS bundle has two distinct package paths:

- `pyodide.loadPackagesFromImports(cell_source)` for Pyodide-bundled
  scientific packages (numpy, pandas, scipy, sklearn, matplotlib,
  sympy, nilearn, nibabel…) — auto-loaded by AST-scanning cell code.
- `micropip.install(<hardcoded list>)` at bootstrap — installs marimo
  itself plus a fixed set (jedi, pygments, docutils, pyodide_http, plus
  pandas/duckdb/sqlglot/pyarrow when `mo.sql` or polars is detected).
  The list is baked into the bundle.

For dartbrains-flavoured pages, any third-party package that's
pure-Python on PyPI but not in Pyodide's bundle (the canonical example
being `nltools`) silently fails to import in the browser. There is no
host-page extension hook on the islands runtime. (`transforms/wasm.py:24–53`
documents this in detail.)

**What we did.** marimo-book stages a copy of the notebook with an
auto-generated PEP 723 inline-metadata block, then hands the staged copy
to `MarimoIslandGenerator.from_file`. That block is invisible to the
runtime today, but it's the correct manifest, and it's a useful
prerequisite for `marimo-book sync-deps` (molab portability) and any
future migration to `marimo export html-wasm` (which *does* read PEP
723).

**What would help upstream.** Either:

- `MarimoIslandGenerator.render_head(extra_micropip=[...])` that injects
  the list into the bootstrap. Simplest.
- The islands bundle reads a `<script class="marimo-pep723">{...}</script>`
  block emitted by `render_body()` and merges it into the
  `micropip.install()` list. Cleanly authored from the host page.
- Converge `MarimoIslandGenerator` and `marimo export html-wasm` so they
  share the PEP-723-aware code path.

### 4. No anywidget readiness signal

**Symptom.** Every dartbrains widget had a `requestAnimationFrame(animate)`
loop that read `model.get("trait")` immediately at the end of `render()`.
The trait sync from Python → JS is asynchronous, so for the first ~20–60
frames (~1 s) those traits are `undefined`, and downstream `.toFixed(...)`
calls throw

> TypeError: Cannot read properties of undefined (reading 'toFixed')

at ~60 errors/sec. The widgets self-heal as soon as the user moves any
slider (which forces a sync), so the symptom is cosmetic — but it's a
striking quantity of console noise on first paint, plus widget readouts
display `NaN` until the first interaction.

**What we did.** Two layers in every widget's `*_widget.js`:

- A read-site fallback: every `model.get("trait")` call gets a JS-side
  default mirroring the Python `traitlets.X(default).tag(sync=True)`
  default (`?? 3.0`, `?? 0.0`, `?? "spin_echo"`, etc.). `??` not `||`
  because some traits are legitimately falsy (`paused=false`,
  numeric `0.0`).
- A log-once try/catch wrapper around the body of every `animate()`,
  using a closure-captured `let _animateErrLogged = false;` flag so
  any future trait-name typo can't silently spam the console.

This shipped as `dartbrains-tools 0.1.1` and eliminated 374 errors/sec
across the live MR_Physics + Preprocessing pages.

**What would help upstream.** anywidget could expose either:

- A synthetic `model-synced` event the widget can listen for.
- A `model.ready: Promise<void>` that resolves once the initial trait
  sync completes.

Either would let widget authors `await model.ready` before kicking off
the rAF loop. Today the widget-side workaround is ours to maintain in
every widget's source.

### 5. Static output is a derived view, not a primary mode

**Symptom.** Booting Pyodide on every page is too heavy: the WASM
bootstrap pulls Pyodide + scientific stack (~30+ MB) and the GitHub
Actions runner needs ~30 GB of free disk to build it, which we already
hit — see commit `544d2e6` ("free ~30 GB of unused preinstalled
tooling"). For dartbrains we want WASM only on pages that need true
reactivity (MR_Physics, Signal_Processing, Preprocessing) and static
output everywhere else.

**What we did.** A 1143-LOC `precompute.py` that essentially re-runs the
notebook N times across an enumerated UIElement value space, captures
cell HTML deltas, and bakes a giant lookup table the JS shim uses to
swap `cell.innerHTML` on slider input. It works — the ICA notebook
ships a working component-slider this way — but the lookup table can
hit 6.49 MB inlined into one HTML file because brain-plot iframes
contain base64-embedded slices.

**Pain points along the way.**

- The precompute scanner only detects literal slider bounds in source.
  A dynamic `stop=len(output['components'])-1` silently renders frozen.
  We have hardcoded `stop=9` in dartbrains' `ICA.py` with a comment
  explaining why.
- The precompute system has its own slider-hydration shim, separate
  from the WASM-mode marimo-slider hydration. In static + precompute
  mode the `<marimo-slider>` element is a 0×0 dormant placeholder while
  the live control is the `<input type="range">` injected into
  `.marimo-book-precompute-control`. We chased the dormant element
  during a debugging session before realising the live one was already
  working — comments would be a separate blast radius from upstream
  behaviour, but the parallelism is confusing.

**What would help upstream.** A first-class build-time mode in marimo
itself:

```python
gen = MarimoStaticGenerator.from_file("nb.py")
await gen.build(precompute={"component_slider": range(10)})
html = gen.render(mode="static")  # one html per value combo
```

Today, "static reactivity" is fundamentally a workaround for the
runtime being heavy, and lives entirely in marimo-book reimplementing
the kernel's reactivity graph. If `MarimoIslandGenerator` had a
`build_precomputed(values=...)` mode returning `{value_combo: cell_html}`,
`precompute.py` would shrink by ~80%.

## Smaller paper cuts (one-liners worth fixing)

- `include_init_island=False` is a magic kwarg we discovered
  empirically. The kernel-driven hide-trigger for the spinner doesn't
  fire reliably, so we skip it entirely. (`transforms/wasm.py:128–133`)
- `MarimoIslandGenerator.from_file()` requires a real path; we have to
  materialise the staged-with-PEP-723 copy to disk. An
  `from_string(src)` overload would eliminate the temp-file dance.
- `gen.render_body(style="")` to suppress marimo's default
  `max-width:740px` wrapper. Surprising default for a renderer designed
  to be embedded into a host page that already controls width.
- Material's `navigation.instant` re-creates `<script>` tags on page
  swap and chokes on JSON-content scripts ("Unexpected token ':'"),
  silently dropping the script. We had to switch every JSON payload to
  `<template>` blocks (`marimo_book.js:317–330`). This is a Material
  bug at heart, but a marimo-issued
  `<script type="application/marimo-json">` (with a non-conflicting
  MIME) would dodge it.
- `<marimo-ui-element>.object-id` stability across kernel re-render is
  undocumented but load-bearing for our driver registry. If marimo ever
  changes that allocation algorithm, our registry silently misses. A
  one-line "object-id is stable across re-renders within a session"
  guarantee in the docs would make us less nervous.
- `MarimoIslandGenerator.build()` is async-only (`asyncio.run` wrapper
  required) and not incremental. A 40-cell notebook re-runs all 40
  cells on any change. A per-cell hash + cache hook would make `marimo-book`
  builds dramatically cheaper on rebuild.

## What would unblock the next wave

If we could ask the marimo team for one thing, it would be a
**documented, supported "static-first" path** that takes:

- a `.py` notebook,
- a PEP 723 manifest (or `extra_micropip` list),
- an optional `{ui_var: [values]}` enumeration for precompute mode,

and returns either pure HTML (precomputed across the value space) or
HTML + WASM bundle (live kernel), without consumers reaching into runtime
internals. Something concretely like:

```python
gen = MarimoStaticGenerator.from_file("notebook.py")
await gen.build(
    precompute={"component_slider": range(10)},
    extra_micropip=["nltools"],
)
html = gen.render(mode="static")    # or "wasm"
binding_map = gen.binding_map()      # {(class, trait): object_id}
```

`marimo-book` would then be a thin Jupyter-Book-2-shaped wrapper around
that, instead of a 4700-LOC reimplementation of half the runtime in
Python + JS.

## Concrete code pointers (for anyone reading marimo-book alongside)

The comment blocks below are de facto bug reports:

- `src/marimo_book/transforms/anywidgets.py:317–331` — explains the AST
  driver-injection pipeline.
- `src/marimo_book/transforms/anywidgets.py:450–474` — "Why three
  storage locations" for the driver map.
- `src/marimo_book/transforms/wasm.py:24–83` — anywidget data-URL trust
  check + PEP 723 propagation gap.
- `src/marimo_book/assets/marimo_book.js:232–269` — runtime
  `MutationObserver` intercept for runtime-emitted `<marimo-anywidget>`.
- `src/marimo_book/assets/marimo_book.js:317–330` — `<template>` switch
  for surviving Material's `navigation.instant`.

Each is a few paragraphs of explanation followed by code that would
collapse to a one-liner if the upstream API exposed the corresponding
hook.

## Closing

The good news: we shipped a working prototype, dartbrains.org is live
and reactive on every page that needs to be. The friction documented
here is genuine and accumulated over real production work, but none of
it is fatal — workarounds exist, are tested, and are stable enough to
deploy. The point of writing this down isn't to complain; it's to
surface the design pressure we've been under, so the marimo team can
weigh how much of it is worth absorbing into the runtime API and how
much is just "this is what publishing-pipeline consumers always look
like."

If marimo wants a reference implementation of a static-first consumer
of the islands API, marimo-book is it. We're happy to upstream patches,
turn any of the above into individual issues, or pair with the marimo
team on prototypes for a `MarimoStaticGenerator` API.
