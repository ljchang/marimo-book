# Design: `api_docs` — auto-generated Python API reference

**Status:** Approved (2026-06-04)
**Feature flag:** `api_docs.enabled` in `book.yml`
**Extra:** `marimo-book[api]`

## Summary

Add an opt-in feature that auto-generates a Python **API Reference** section
for a book's companion package(s) from their docstrings. The preprocessor
loads each package with **Griffe** (the same loader [mkdocstrings] renders
with), walks its public modules, stages one `::: pkg.module` directive page
per module into the `_site_src/` tree, and splices a nested "API Reference"
section into the nav — mirroring how `include_changelog` and `blog` append
nav entries today. The generated `mkdocs.yml` gains an `mkdocstrings` plugin
block that renders those directives at build time.

[mkdocstrings]: https://mkdocstrings.github.io/

## Motivation

A marimo-book often documents a real installable Python library (the
scientific-Python / fMRI audience: `nltools`, dartbrains, etc.). Hand-writing
and maintaining an API reference is tedious and drifts from the code.
mkdocstrings + Griffe is the de-facto standard for docstring-driven API docs
in the MkDocs world; this feature wires it into marimo-book's pipeline so a
user gets a complete, always-current API section from a few lines of
`book.yml`.

## Scope

**In scope (v1):**

- Auto-generate one staged page per public module, with a nested nav section.
- Resolve package source two ways: a source **path** (Griffe reads the AST
  directly, no install needed) and/or an **importable dotted name** from the
  build environment.
- Configurable docstring style, nav title, output dir, module excludes, and a
  passthrough `options` dict for the full mkdocstrings Python-handler surface.

**Out of scope (deferred):**

- A native `git:` source that clones another repo at build time. Fully
  substitutable today by pinning that repo as one of the book's own
  dependencies (`pip install 'git+https://…@ref'`) so it resolves by import
  name. Network/auth/ref-pinning complexity isn't worth it for v1. The config
  is designed to extend to this cleanly later (a `source` discriminator).
- Versioned/multi-version API docs (mike-style).
- Dogfooding marimo-book's own API on the self-hosted docs site — see
  "Dogfood" below; deferred to a follow-up PR to avoid gating the core feature
  on docstring cleanup under `--strict`.

## Design decisions (resolved during brainstorming)

| Question | Decision |
|---|---|
| Primary use case | A **companion Python package** the book documents. |
| Automation level | **Fully auto, one page per module** (not single-page, not manual). |
| Source resolution | **Both** configurable source paths **and** importable names. |
| `git:` clone-at-build | **Deferred** to a later version. |
| Default docstring style | **google** (mkdocstrings/Griffe default; configurable). |
| Page/nav generation | **marimo-book generates it** (Approach A), not the
  `gen-files`+`literate-nav` community recipe (Approach B). Honors the
  "preprocessor emits artifacts" and "marimo-book owns the nav" invariants,
  reuses the same Griffe loader mkdocstrings renders with (no page/render
  drift), and ports to the future zensical shell by swapping only the plugin
  block. |

## Architecture

The feature decomposes into three units along the existing seams every
feature flag uses:

1. **Config** (`config.py`) — a nested `ApiDocs` model on `Book`.
2. **Enumeration + staging** (`api_docs.py`, new, shell-neutral) — load
   packages, walk modules, emit `:::` pages, return the nav subtree.
3. **Plugin emission** (`shell.py:_build_config`) — emit the `mkdocstrings`
   plugin block into the generated `mkdocs.yml` (the only shell-specific part).

Wiring lives in `preprocessor.py` alongside the changelog/blog nav appends.

### 1. Config schema (`config.py`)

```python
class ApiDocs(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    packages: list[str] = Field(default_factory=list)       # importable/dotted names
    paths: list[Path] = Field(default_factory=list)         # source search dirs, rel. to book root
    docstring_style: Literal["google", "numpy", "sphinx"] = "google"
    title: str = "API Reference"                            # nav section label
    dir: str = "api"                                        # staged output subdir
    exclude: list[str] = Field(default_factory=list)        # dotted module globs to skip
    options: dict[str, Any] = Field(default_factory=dict)   # passthrough → python handler options
    inventories: list[str] = Field(default_factory=list)    # objects.inv URLs for cross-links

    @model_validator(mode="after")
    def _require_packages(self):
        if self.enabled and not self.packages:
            raise ValueError("api_docs.enabled is true but no packages: were listed")
        return self
```

Added to `Book`: `api_docs: ApiDocs = Field(default_factory=ApiDocs)`. `paths`
resolve relative to the book root at build time (like `bibliography.files`).

Example `book.yml`:

```yaml
api_docs:
  enabled: true
  packages: ["mypkg"]
  paths: ["../src"]
  docstring_style: google
  title: "API Reference"
  exclude: ["mypkg.tests*"]
  options:
    members_order: source
    show_root_full_path: false
```

The `options: {}` passthrough is the deliberate escape hatch that keeps the
schema small: marimo-book sets a few sensible defaults and deep-merges the
user's `options` on top, so power users get the full ~40-option Python-handler
surface while casual users touch one knob (`docstring_style`).

### 2. Enumeration + page staging (`src/marimo_book/api_docs.py`, new)

Single-purpose, shell-neutral. Public entry point:

```python
def stage_api_docs(cfg: ApiDocs, *, book_root: Path, docs_dir: Path) -> list[dict | str]:
    """Load each package via Griffe, stage one :::-directive page per module,
    and return the nav subtree to splice under cfg.title."""
```

Behavior:

- Load each package with `griffe.load(name, search_paths=[resolved paths…])`
  — AST-based, no import side effects, and the *same* loader mkdocstrings
  renders with, so the staged page set can't drift from what renders.
- Walk the module tree recursively. For each module, emit a minimal page —
  `# <title>` + `::: pkg.module` — into `docs_dir/<dir>/…`:
  - top package `pkg` → `api/pkg/index.md` (`::: pkg`)
  - leaf module `pkg.sub` → `api/pkg/sub.md`
  - subpackage `pkg.sub` (has children) → `api/pkg/sub/index.md` + children
- **Public filter:** skip modules whose final name starts with `_` (keep
  `__init__`), plus anything matching an `exclude` glob.
- Return a nested nav subtree mirroring package structure, e.g.
  `[{"API Reference": [{"mypkg": ["api/mypkg/index.md", {"core": "api/mypkg/core.md"}]}]}]`.
- **`ImportError` guard:** if Griffe/mkdocstrings is not importable, raise a
  friendly `pip install 'marimo-book[api]'` error (mirrors how other missing
  extras surface).

Staged pages live under the normal `_site_src/` tree mkdocs consumes; they are
real staged content (not `staged_sibling_file()` temp siblings), so the
orphan-cleanup sweep leaves them alone.

### 3. Preprocessor wiring (`preprocessor.py`)

One block alongside the existing changelog/blog nav appends (~line 528):

```python
if self.book.api_docs.enabled:
    api_nav = stage_api_docs(self.book.api_docs, book_root=self.root, docs_dir=docs_dir)
    nav.extend(api_nav)
```

### 4. Plugin emission (`shell.py:_build_config`)

A new branch in the existing plugin-assembly chain, after `search`:

```python
if book.api_docs.enabled:
    handler_opts = {
        "docstring_style": book.api_docs.docstring_style,
        "show_source": True,
        "show_root_heading": True,
        "show_submodules": False,   # each submodule has its own page
        **book.api_docs.options,    # user overrides win
    }
    python_handler: dict[str, Any] = {"options": handler_opts}
    if book.api_docs.paths:
        python_handler["paths"] = [str(p) for p in resolved_paths]   # absolute
    if book.api_docs.inventories:
        python_handler["inventories"] = book.api_docs.inventories
    plugins.append({"mkdocstrings": {"handlers": {"python": python_handler}}})
```

**Path resolution:** the generated `mkdocs.yml` lives in the staged tree, not
at the book root, so book-root-relative `api_docs.paths` are resolved to
**absolute** paths before being written into the `paths` key (otherwise
mkdocstrings would resolve them against the staged config's directory). The
preprocessor resolves them against the book root and passes the absolute paths
through to `emit_mkdocs_yml`.

`autorefs` is already a base dep; when `cross_references` is on, mkdocstrings
auto-integrates so prose can link to API objects (`[mypkg.Thing][]`) with no
extra wiring.

**Shell-agnostic note:** the staged pages + nav (unit 2) are shell-neutral.
Only this plugin block is mkdocs-specific. The future zensical shell emits a
`[project.plugins.mkdocstrings.handlers.python]` TOML block with the same keys
and reuses units 1–3 untouched.

### 5. Packaging + CI

- `pyproject.toml`: new extra `api = ["mkdocstrings[python]>=1.0"]` (pulls
  mkdocstrings, mkdocstrings-python, Griffe).
- `.github/workflows/ci.yml` **and** `docs.yml`: add `[api]` to installed
  extras (CLAUDE.md rule: the docs job installs every extra the docs site
  uses).

### 6. Error handling

| Condition | Behavior |
|---|---|
| `enabled: true`, no `packages` | pydantic validation error at config load (fail fast). |
| package not loadable by Griffe (bad name / not on paths) | build error naming the package + the paths searched. |
| `mkdocstrings`/Griffe not installed | friendly `pip install 'marimo-book[api]'` error at preprocess. |
| `--strict` + docstring warnings | mkdocs surfaces them; non-strict builds still succeed. |

A misconfigured API section **fails the build** rather than silently emitting
an empty section — wrong package names should be loud.

### 7. Tests (`tests/test_api_docs.py` + fixture)

- Fixture package under `tests/fixtures/` (e.g. `sample_pkg/` with
  `__init__.py`, `core.py`, a subpackage, and a `_private.py`) carrying
  Google-style docstrings.
- Cases:
  - enumeration walks the full module tree;
  - private modules + `exclude` globs are skipped;
  - staged page contents contain the right `::: sample_pkg.core` directive;
  - nav structure matches package nesting;
  - `paths`-based load works without the package installed;
  - unknown package raises a clear build error;
  - flag-off is a complete no-op (no `api/` dir, no plugin).
- Shell/preprocessor test: `emit_mkdocs_yml` includes the `mkdocstrings`
  plugin with merged handler options when enabled, and omits it when off.

### 8. Docs to update (same PR)

- CLAUDE.md feature-flag table: new `api_docs` row.
- CHANGELOG `[Unreleased]`.
- A short authoring guide page in `docs/` covering the `book.yml` knobs and
  the "pin a git repo as a dependency" pattern for cross-repo packages.

## Dogfood (deferred follow-up)

Adding an `api_docs` section to `docs/book.yml` pointing at `marimo_book`
itself is an excellent real-world test + demo, but `docs.yml` builds with
`--strict`, and mkdocstrings emits warnings on missing/malformed docstrings
that strict mode treats as errors. To avoid gating the core feature on a
docstring-cleanup pass, dogfood lands in a separate follow-up PR.
