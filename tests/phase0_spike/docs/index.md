# Phase 0a: Material for MkDocs feasibility

This is a throwaway site used by marimo-book's Phase 0a spike to verify that
Material for MkDocs can render everything the preprocessor will emit in v0.1.

## Pages

- [Prose + math + admonitions](prose.md) — checks `pymdownx.blocks.admonition`, `pymdownx.details`, `pymdownx.arithmatex`, fenced code with copy.
- [Anywidget-style script](widget.md) — checks that a raw `<script type="module">` + mount `<div>` with `dataset` attrs survives the markdown pipeline intact.
- [Raw plotly output](plotly.md) — checks that a raw plotly `<div>` + inline `<script>` renders.
- **Sidebar scale** — the "Sidebar scale test" section has 10 pages to confirm the sidebar scales and collapses cleanly at depth.

## Checklist

- [ ] Dark-mode toggle works and persists
- [ ] Search box opens with `/` and finds body text
- [ ] Code blocks have copy buttons
- [ ] Palette matches what we set in `mkdocs.yml` + `stylesheets/extra.css`
- [ ] Every admonition type renders with its color + icon
- [ ] Math renders inline and as blocks
- [ ] Anywidget mount `<div>` + `<script>` reaches the DOM
- [ ] Plotly HTML renders a chart
- [ ] Sidebar is navigable at 10+ entries
