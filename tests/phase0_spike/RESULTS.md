# Phase 0a — Material for MkDocs feasibility spike: results

**Date:** 2026-04-24
**Outcome:** GREEN — proceed with Material-for-MkDocs shell for v0.1.

## Environment

- Python 3.13.12
- mkdocs 1.6.1
- mkdocs-material 9.7.6
- pymdown-extensions 10.21.2

## Build

```
mkdocs build --strict
# Documentation built in 0.14 seconds
```

No warnings or errors under `--strict`.

## Verification checklist

| Capability | Target page | Result |
|---|---|---|
| Raw `<div class="marimo-book-anywidget" data-*>` survives | `widget.md` | PASS — mount `<div>` + `data-widget`, `data-b0` attrs present in rendered HTML |
| `<script type="module">` survives | `widget.md` | PASS — script tag lands in DOM verbatim |
| Raw plotly `<div id>` + `<script src>` + inline JS | `plotly.md` | PASS — `Plotly.newPlot`, plotly CDN `src`, `id="plotly-chart"` all present |
| 6 admonition types: note / tip / warning / danger / important / seealso | `prose.md` | PASS — all 6 render with `class="admonition <type>"` |
| Math (inline, block, amsmath `align`) via `pymdownx.arithmatex` | `prose.md` | PASS — 3 arithmatex spans in output |
| Custom palette via `stylesheets/extra.css` | all | PASS — Dartmouth green vars loaded, `stylesheets/extra.css` referenced on every page |
| Dark-mode toggle (default + slate schemes) | all | PASS — `data-md-color-scheme` switches between `default` / `slate` |
| Search index built + body text indexed | all | PASS — `search_index.json` has 22 docs including all page titles + section headings |
| Multi-level sidebar with 10+ leaf entries | `many/*` | PASS — all 10 `many/pageNN.md` entries rendered, sidebar navigable |

## Notable warning (informational, not blocking)

Material for MkDocs 9.7.6 prints a banner on every build warning that MkDocs
2.0 will break all Material plugins, themes, and the migration path is
closed. This reinforces the plan's zensical-upgrade-path decision — the
Material team publicly positions zensical as the actual successor. We avoid
MkDocs 2.0 entirely and target zensical for v0.3.

## Proceed signal for Phase 1

- `.py → .md + inline HTML` preprocessor output is compatible with Material.
- No need to invent a custom markdown extension or plugin — standard
  `pymdownx.*` + Material handle everything.
- Anywidget JS bundles can be referenced from `<script type="module" src="/Code/js/…">`
  without directive support — the preprocessor gets simpler than the JB2
  parser.
