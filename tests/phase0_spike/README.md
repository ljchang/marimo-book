# Phase 0a: Material for MkDocs feasibility spike

This directory is a self-contained mkdocs site used to verify that
Material for MkDocs can render everything marimo-book's preprocessor will
emit in v0.1:

1. **Prose + admonitions + math** (pymdownx + arithmatex)
2. **Inline anywidget-style `<script type="module">`** (raw HTML + dataset attrs)
3. **Raw plotly HTML output block**
4. Custom theme overrides (palette, logo, CSS), sidebar scaling, search
   indexing of body text and code.

## Run the spike

```bash
cd tests/phase0_spike
pip install mkdocs-material>=9.5 mkdocs-material[imaging] pymdown-extensions
mkdocs serve
# open http://127.0.0.1:8000
```

## Verification checklist

| Capability | Target page | Expected |
|---|---|---|
| Admonitions (note/warning/tip/danger) | `prose.md` | Renders with colored blocks + icons |
| Dropdown admonition (`???`) | `prose.md` | Collapsible block |
| Inline math `$x^2$` + block `$$…$$` | `prose.md` | KaTeX/MathJax-rendered |
| Raw `<script type="module">` + mount `<div>` | `widget.md` | Script loads; `dataset` attrs accessible |
| Raw plotly `<div>` + inline `<script>` | `plotly.md` | Plotly chart renders |
| Multi-level sidebar with 30+ entries | `many/*.md` | Sidebar scrollable, collapsible |
| Full-text search over prose + cell source | any | `/` opens search; results highlight |
| Dark-mode toggle | any | Persists across navigation |
| Custom palette (Dartmouth green) | any | Header colored correctly |

Notes from the run are written to `RESULTS.md` in this directory.
