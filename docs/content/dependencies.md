# Notebook dependencies

Marimo re-executes every notebook at build time to capture cell outputs.
That means the Python environment running `marimo-book build` has to
satisfy each notebook's `import` statements. `marimo-book` supports two
strategies for provisioning those deps; pick in `book.yml`:

```yaml
dependencies:
  mode: env       # default
  # mode: sandbox
```

## `env` mode (default)

The Python environment that invoked `marimo-book` provides every
notebook's deps. The typical setup:

```bash
# In your book's repo:
cat pyproject.toml
# [project]
# dependencies = ["marimo-book", "numpy", "pandas", "nltools", ...]

uv pip install -e .
marimo-book build
```

**When this is the right choice:**

- All notebooks share the same dep stack (a tutorial book for one
  library, a course using one domain toolkit).
- You're iterating fast in `marimo-book serve` — no overhead per
  rebuild.
- You already manage a `pyproject.toml` / `requirements.txt`.

**Tradeoffs:**

- If two notebooks need incompatible package versions, you're stuck.
- Portability: the notebooks aren't self-contained; someone cloning the
  book needs to know what to install.

## `sandbox` mode

Each notebook declares its own deps with a [PEP 723 inline metadata
header](https://peps.python.org/pep-0723/):

```python
# /// script
# dependencies = [
#     "marimo>=0.23",
#     "numpy>=2.0",
#     "pandas>=2.0",
# ]
# ///

import marimo

__generated_with = "0.23.2"
app = marimo.App()
# ...
```

At build time, `marimo-book` passes `--sandbox` to marimo, which uses
[`uv`](https://docs.astral.sh/uv/) to provision a fresh isolated
environment per notebook. After the first run, `uv`'s package cache
makes subsequent runs fast.

**When this is the right choice:**

- Notebooks need incompatible dep versions.
- You want portability — a reader can grab any single `.py` and run it
  anywhere `uv` is installed, no project file needed.
- CI reproducibility — pinning exact versions in each notebook's
  header freezes behaviour.

**Tradeoffs:**

- First build per notebook is ~5–10 s slower.
- Requires `uv` to be installed on the build machine.

## CLI override

You can force the mode for a single invocation with `--sandbox` or
`--no-sandbox`:

```bash
marimo-book build --sandbox         # force sandbox even if book.yml says env
marimo-book build --no-sandbox      # force env even if book.yml says sandbox
marimo-book serve --sandbox         # slower loop, but reproducible
```

Common pattern: keep `dependencies.mode: env` in `book.yml` for local
dev, then pass `--sandbox` in your CI workflow for the published build:

```yaml
# .github/workflows/deploy.yml
- run: pip install marimo-book
- run: marimo-book build --sandbox --strict
```

## Which mode is dartbrains using?

Dartbrains (the reference consumer) uses `env` mode. The repo has a
`pyproject.toml` with the full scientific stack (`nltools`, `numpy`,
`nibabel`, `nilearn`, …) and runs `marimo-book` from its own venv.
That's the right call when all notebooks share the same dependencies,
which is typical for a course or long-form tutorial.

## Auto-generated PEP 723 blocks + WASM micropip bootstrap

`marimo-book` walks each notebook's AST, derives a dependency list
(via marimo's own ~777-entry import → distribution mapping table),
and stages a build-time copy with two things injected:

1. A **PEP 723 `# /// script` block** at the top of the file. This is
   the standard inline-script-metadata format read by `uv run`,
   `marimo --sandbox`, molab, and any other PEP-723-aware tool.
2. For WASM-mode pages only, a **`micropip` bootstrap** prepended to
   the first `@app.cell` function:
   ```python
   try:
       import micropip
       await micropip.install(["nltools", "numpy", ...])
   except ImportError:
       pass
   ```
   This is necessary because the marimo islands JS bundle that
   renders WASM pages has no codepath for reading PEP 723 itself —
   it auto-loads only Pyodide-bundled scientific packages
   (numpy/pandas/scipy/sklearn/matplotlib/nilearn/nibabel/…) via
   `loadPackagesFromImports`. Pure-Python PyPI-only deps (`nltools`
   is the canonical case) silently fail to import without an
   explicit `micropip.install`. Pyodide's micropip filters out
   anything already in `sys.modules`, so passing the full dependency
   list is safe — bundled packages no-op, non-bundled ones install.

   The `try/except ImportError` makes the cell safe to execute
   under build-time CPython (where `micropip` doesn't exist) — only
   the in-browser run actually installs.

Your source `.py` files are never modified by the build.

**For WASM pages, both injections are unconditional** — those pages
don't work without them. For static or sandbox pages, opt in to the
PEP 723 block via `book.yml`:

```yaml
dependencies:
  mode: env
  auto_pep723: true                # generate blocks for static + sandbox pages too
  pin: env                         # optional: pin to currently-installed versions
  extras: ["nltools>=0.5"]         # always-include entries (NOT mapped through table)
  overrides:                       # manual import-name → distribution-name remappings
    my_internal_module: my-internal-pkg
  requires_python: ">=3.11"        # default: derive from running interpreter
```

### Resolution rules

- **Stdlib filter** uses `sys.stdlib_module_names | sys.builtin_module_names`,
  so `os`, `pathlib`, `json`, etc. are never listed.
- **`marimo` itself** is filtered out (the islands runtime provides it).
- **Relative imports** (`from . import x`) are skipped — they resolve
  locally, not on PyPI.
- **Distribution mapping** uses marimo's own ~777-entry table — the
  same mapping the Pyodide kernel applies for fallback resolution.
  `PIL` → `Pillow`, `cv2` → `opencv-python`, `sklearn` → `scikit-learn`,
  `bs4` → `beautifulsoup4`, etc. Names absent from the table fall back
  to `name.replace("_", "-")`. User-supplied `overrides` win over both.
- **Extras** are written verbatim alongside detected imports. An extra
  whose distribution name matches a detected import wins (so its version
  specifier is preserved).

### `marimo-book sync-deps`

The build never modifies your `.py` files. To commit the auto-generated
blocks back into your source (so they're under version control and
work for `molab`, sharing, or anyone running the notebooks outside
marimo-book), run:

```bash
marimo-book sync-deps                # writes/updates blocks in place
marimo-book sync-deps --check        # dry-run; exits non-zero if any file would change
```

The writer is **non-destructive**: existing `requires-python`,
`[tool.uv]` tables, and hand-curated dependency entries are preserved.
New detected dependencies are merged in by canonical distribution
name. Running `sync-deps` twice in a row is a no-op.

`sync-deps --check` is suitable for a CI hook to keep notebook headers
fresh against the rest of your project's deps.
