# Phase 0b — Dartbrains syntax inventory

**Date:** 2026-04-24
**Source:** `ljchang/dartbrains@v2-marimo-migration`, grep over `content/*.md`
and `content/*.py`. Generated `*.ipynb` files excluded (artifacts of the JB2
parser that we're replacing).

## MyST syntax actually used in dartbrains

| Directive / role | Count | Used in | v0.1 scope | Notes |
|---|---|---|---|---|
| `:::{anywidget} <js>` | many | generated `.ipynb` only | **N/A** | These are JB2-parser artifacts; the new pipeline emits `<div class="marimo-book-anywidget" data-*>` + `<script type="module">` instead. Zero in source files. |
| `:::{glossary}` | 15 | `Glossary.md` only | **Yes** | Trivial — strip `:::{glossary}` fence; definition-list content underneath is standard markdown. Material renders definition lists natively. |
| `{download}\`label <path>\`` | 16 | 5 `.md` + 1 `.ipynb` | **Yes** | Trivial regex: `{download}\`X <path>\`` → `[X](path)`. Paths are relative to content/. |
| `(label)=` cross-ref anchors | 3 | 3 `.py` files | **Yes (minimal)** | `(run-preprocessing)=`, `(multivariate-decomposition)=`, `(content:group_analysis:labels)=`. Emit `<a id="label"></a>` or `{#label}` attr-list at the anchor point. |

## MyST syntax NOT used in dartbrains

Zero occurrences across all content — can be deferred to v0.2 or skipped
entirely for v0.1:

- Admonitions (`:::{note}`, `:::{tip}`, `:::{warning}`, `:::{danger}`,
  `:::{important}`, `:::{hint}`, `:::{caution}`, `:::{seealso}`, `:::{info}`,
  `:::{success}`, `:::{error}`). Marimo callouts (`mo.callout`) in `.py`
  files are rendered by marimo's own HTML export, not as MyST syntax.
- Cross-ref roles: `{ref}`, `{eq}`, `{numref}`, `{doc}`, `{term}`
- Citation roles: `{cite}`, `{cite:p}`, `{cite:t}`, `[@key]`, BibTeX
- Figure directives: `{figure}`, `{subfigure}`, figure numbering
- Equation numbering with labels
- Special directives: `{card}`, `{grid}`, `{tab-set}`, `{tab-item}`,
  `{prf:}`, `{example}`, `{proof}`, `{theorem}`, `{aside}`
- `{autolink}`, `{sub}`, `{sup}`, `{kbd}`, `{exec}`, `{subst}`
- MyST slide breaks (`+++`), frontmatter blocks (`---`)

## Implications for v0.1 preprocessor scope

Only four preprocessor transforms need to ship in v0.1:

1. **`marimo_export.py`** — `.py → .md + inline HTML` (the big one, reuses
   marimo's own HTML export)
2. **`download_role.py`** — `{download}\`label <path>\`` → `[label](path)`
   (~20 LOC)
3. **`glossary_directive.py`** — strip `:::{glossary}` / `:::` fencing
   (~15 LOC)
4. **`crossref.py`** — `(label)=` anchor emission only. No `{ref}` /
   `{numref}` / `{eq}` resolution needed for dartbrains. (~30 LOC)

Deferred to v0.2 (YAGNI for v0.1):

- `admonitions.py` — MyST `:::{note}` → Material `!!! note` syntax bridge.
  Not used in dartbrains `.md` files. If used later, it's a 30-line regex.
- `citations.py` — BibTeX + `{cite}` / `[@key]`. Zero usage.
- `figures.py` — `{figure}` + numbering. Zero usage.
- `equations.py` — `{eq}` refs + math macros. Zero usage.
- General `{ref}` / `{numref}` / `{doc}` / `{term}` role resolver. Zero
  usage.

## Impact on the plan

The original v0.1 scope estimated ~400 LOC across 8 transform modules. The
inventory narrows this to ~200 LOC across 4 transform modules. The
feature-matrix table in the plan is still technically correct (Material
provides admonitions etc. natively), but the **preprocessor work for v0.1
is about half of what we estimated**.

This reinforces the dartbrains-driven MVP strategy: v0.1 ships what
dartbrains needs and nothing more. Admonition / citation / figure
preprocessor transforms are deferred to v0.2 and will be added when a
consumer actually needs them.
