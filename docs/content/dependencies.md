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
