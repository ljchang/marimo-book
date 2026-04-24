# Anywidget-style mount

This page verifies the critical seam for our preprocessor's `static`-mode
output: a raw `<div>` mount carrying model defaults on `data-*` attributes,
plus a `<script type="module">` that would load an anywidget ES module.

## The mount

<div id="demo-mount" class="marimo-book-anywidget"
     data-widget="demo" data-b0="3.0" data-n-protons="100"
     data-paused="false"
     style="min-height: 140px; border: 1px dashed #bbb; padding: 1em;">
  <em>(widget mount — script should replace this content on load)</em>
</div>

<script type="module">
  // Inlined for the spike; in production the preprocessor would reference
  // a JS module under /Code/js/ via a src attribute.
  const mount = document.getElementById('demo-mount');
  if (mount) {
    const ds = mount.dataset;
    mount.innerHTML = `
      <div><strong>demo widget reached the DOM</strong></div>
      <div>widget: <code>${ds.widget}</code></div>
      <div>b0: <code>${ds.b0}</code></div>
      <div>n-protons: <code>${ds.nProtons}</code></div>
      <div>paused: <code>${ds.paused}</code></div>
    `;
    mount.style.borderStyle = 'solid';
    mount.style.borderColor = '#00693E';
  }
</script>

## Why this matters

The current dartbrains pipeline emits `:::{anywidget}` MyST directives. In
marimo-book v0.1 we'll emit this pattern instead:

- `<div class="marimo-book-anywidget" data-widget="…" data-*>` for model defaults
- `<script type="module" src="/Code/js/…_widget.js">` for the behavior

If Material's markdown pipeline leaves this HTML untouched, we're good.
