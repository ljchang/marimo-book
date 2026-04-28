"""Notebook dependency analysis: PEP 723 generation + WASM micropip bootstrap.

Two related transforms operate on a marimo ``.py`` notebook source:

1. **PEP 723 inline-script-metadata** — extract imports, map to PyPI
   distribution names via marimo's own table, and write/merge a
   ``# /// script`` block at the top of the file. This is the
   manifest format ``uv run --script`` and ``marimo --sandbox`` read.
   Used by the build for sandbox-mode pages and by ``sync-deps`` for
   committing the block back into source for ``molab`` portability.

2. **WASM micropip bootstrap** — for pages rendered through
   ``MarimoIslandGenerator`` (WASM mode), AST-inject a try/except
   ``await micropip.install([...])`` block at the top of the first
   ``@app.cell`` function. The islands JS bundle has no codepath that
   reads PEP 723 (we verified empirically — it auto-loads only
   Pyodide-bundled packages via ``loadPackagesFromImports``), so we
   ship the install call inside cell code instead. Pyodide's micropip
   filters out packages already in ``sys.modules`` from
   ``loadPackagesFromImports``, so passing the full ``derive_dependencies()``
   list is safe — bundled deps no-op, non-bundled deps install. The
   try/except wraps ``ImportError`` so build-time CPython execution
   (where ``micropip`` doesn't exist) doesn't crash.

The module is pure: no I/O, no subprocess shelling. Callers
(``preprocessor._maybe_stage_with_pep723`` and the ``sync-deps`` CLI)
read source from disk, call these helpers, and write back where
appropriate.

Reuses marimo's own helpers so that what we write matches what the
WASM kernel will resolve at runtime:

- ``marimo._runtime.packages.module_name_to_pypi_name`` — the same
  mapping table marimo uses for its own micropip fallback resolution.
- ``marimo._utils.scripts.read_pyproject_from_script`` — the PEP 723
  reference parser.
- ``marimo._utils.scripts.wrap_script_metadata`` — adds ``# `` prefixes
  to a TOML body.
"""

from __future__ import annotations

import ast
import re
import sys
from collections.abc import Iterable, Mapping, Sequence
from functools import lru_cache
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from typing import Literal

import tomlkit
from marimo._runtime.packages.module_name_to_pypi_name import module_name_to_pypi_name
from marimo._utils.scripts import read_pyproject_from_script, wrap_script_metadata

PinMode = Literal["none", "env"]

# Marimo itself is provided by the islands runtime (WASM) and by the
# build environment (static/sandbox); never list it as a dependency.
_PROVIDED_MODULES: frozenset[str] = frozenset({"marimo"})

# Match a PEP 723 ``script`` block for in-place replacement. Anchored
# loosely to mirror marimo's own parser (``marimo._utils.scripts.REGEX``).
# The regex consumes the trailing newline of the closing ``# ///`` line,
# so substitution preserves whatever whitespace followed the block.
_BLOCK_RE = re.compile(
    r"^# /// script[ \t]*\n(?:^#(?:[ \t].*)?\n)*?^# ///[ \t]*\n",
    re.MULTILINE,
)


@lru_cache(maxsize=1)
def _stdlib_modules() -> frozenset[str]:
    """Names that should never appear in dependency output.

    ``sys.stdlib_module_names`` is a build-time-frozen frozenset added in
    3.10; combined with ``sys.builtin_module_names`` it covers every
    importable stdlib name across our supported versions (3.11+).
    Critically does NOT use ``pkgutil.iter_modules()`` (which would leak
    every installed third-party package into the filter — autopep723's
    bug).
    """
    return frozenset(sys.stdlib_module_names) | frozenset(sys.builtin_module_names)


def extract_imports(source: str) -> set[str]:
    """Return top-level imported module names, with stdlib + ``marimo`` filtered.

    Walks the AST, collecting the first segment of each ``import`` /
    ``from ... import``. Relative imports (``from . import x``) and
    in-package relative ``from .util import y`` are skipped — they
    resolve locally, not on PyPI.

    Conditional imports inside ``if``/``try``/function bodies are
    collected too. PEP 723 has no notion of conditional dependencies,
    so we list anything that *might* be needed.
    """
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return set()

    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                top = alias.name.split(".", 1)[0]
                if top:
                    names.add(top)
        elif isinstance(node, ast.ImportFrom):
            # ``node.level > 0`` → relative import (``from .util import x``).
            if node.level == 0 and node.module:
                top = node.module.split(".", 1)[0]
                if top:
                    names.add(top)

    return names - _stdlib_modules() - _PROVIDED_MODULES


def map_to_distributions(
    imports: Iterable[str],
    *,
    overrides: Mapping[str, str] | None = None,
) -> list[str]:
    """Map module import names → PyPI distribution names, sorted case-insensitively.

    Resolution order: ``overrides`` (user-provided) → marimo's
    ``module_name_to_pypi_name()`` table → fallback ``name.replace("_", "-")``.
    """
    overrides = dict(overrides) if overrides else {}
    table = module_name_to_pypi_name()
    out: set[str] = set()
    for name in imports:
        if name in overrides:
            out.add(overrides[name])
        elif name in table:
            out.add(table[name])
        else:
            out.add(name.replace("_", "-"))
    return sorted(out, key=str.lower)


def derive_dependencies(
    source: str,
    *,
    extras: Sequence[str] = (),
    overrides: Mapping[str, str] | None = None,
    pin: PinMode = "none",
) -> list[str]:
    """End-to-end: source → sorted PEP 508 requirement strings.

    ``extras`` are always-included entries (e.g. ``["nltools>=0.5"]``);
    they are not run through the import → distribution table. An extra
    that names the same distribution as a detected import wins (its
    version specifier is preserved).
    """
    imports = extract_imports(source)
    dists = map_to_distributions(imports, overrides=overrides)
    if pin == "env":
        dists = [_pin_to_installed(d) for d in dists]

    by_canon: dict[str, str] = {}
    for d in dists:
        by_canon.setdefault(_canonical_name(d), d)
    for e in extras:
        by_canon[_canonical_name(e)] = e

    return sorted(by_canon.values(), key=lambda s: _canonical_name(s))


def has_pep723_block(source: str) -> bool:
    """Whether ``source`` already carries a PEP 723 ``script`` block."""
    return read_pyproject_from_script(source) is not None


def read_existing_dependencies(source: str) -> list[str] | None:
    """Return the existing block's ``dependencies`` array, or ``None`` if no block."""
    project = read_pyproject_from_script(source)
    if project is None:
        return None
    deps = project.get("dependencies")
    if not isinstance(deps, list):
        return []
    return [str(d) for d in deps]


def write_pep723_block(
    source: str,
    deps: Sequence[str],
    *,
    requires_python: str | None = None,
    preserve_existing: bool = True,
) -> str:
    """Insert or update the PEP 723 block; return the new source.

    ``preserve_existing=True`` (default) merges ``deps`` with any
    existing ``dependencies`` array (union by canonical distribution
    name) and preserves all other keys (``requires-python``,
    ``[tool.uv]``, …). Non-destructive — safe to call repeatedly.

    ``preserve_existing=False`` replaces the block wholesale; other
    keys are dropped. Use only when you explicitly want to overwrite a
    user-authored block.

    ``requires_python`` is added only if the existing block (when
    preserved) didn't already specify it. When inserting a brand-new
    block, it's emitted verbatim if provided.
    """
    existing = read_pyproject_from_script(source)

    if existing is not None and preserve_existing:
        new_project: dict = dict(existing)
        merged_deps = list(new_project.get("dependencies", []))
        seen = {_canonical_name(str(d)) for d in merged_deps}
        for d in deps:
            if _canonical_name(d) not in seen:
                merged_deps.append(d)
                seen.add(_canonical_name(d))
        merged_deps.sort(key=lambda s: _canonical_name(str(s)))
        new_project["dependencies"] = merged_deps
        if requires_python is not None and "requires-python" not in new_project:
            new_project["requires-python"] = requires_python
    else:
        new_project = {}
        if requires_python is not None:
            new_project["requires-python"] = requires_python
        new_project["dependencies"] = list(deps)

    new_block = wrap_script_metadata(_dump_block_toml(new_project).rstrip("\n"))

    if existing is not None:
        return _BLOCK_RE.sub(new_block + "\n", source, count=1)
    return _insert_at_top(source, new_block + "\n")


# --- internals --------------------------------------------------------------


def _canonical_name(req: str) -> str:
    """PEP 503-ish normalisation: distribution name only, lowercased, ``_``→``-``."""
    name = str(req).split(";", 1)[0].strip()
    for sep in ("[", "==", ">=", "<=", "!=", "~=", ">", "<", " "):
        idx = name.find(sep)
        if idx >= 0:
            name = name[:idx]
    return name.strip().lower().replace("_", "-")


def _pin_to_installed(dist: str) -> str:
    """Append ``==<installed_version>`` if the distribution is importable, else pass through."""
    canon = _canonical_name(dist)
    try:
        ver = _pkg_version(canon)
    except PackageNotFoundError:
        return dist
    return f"{dist}=={ver}"


def _dump_block_toml(project: Mapping) -> str:
    """Serialize the project mapping as TOML with deterministic key order.

    Order: ``requires-python`` first, ``dependencies`` second, every
    other key after (insertion order). The ``dependencies`` array is
    forced multiline so each entry sits on its own line — the canonical
    PEP 723 layout that ``uv add --script`` produces.
    """
    doc = tomlkit.document()
    for key in ("requires-python", "dependencies"):
        if key not in project:
            continue
        val = project[key]
        if key == "dependencies" and isinstance(val, list):
            arr = tomlkit.array()
            for d in val:
                arr.append(str(d))
            arr.multiline(True)
            doc[key] = arr
        else:
            doc[key] = val
    for key, val in project.items():
        if key not in doc:
            doc[key] = val
    return tomlkit.dumps(doc)


def _insert_at_top(source: str, block: str) -> str:
    """Insert ``block`` at the top of ``source``, after a shebang if present.

    Always leaves a single blank line between the block and the
    following content for readability.
    """
    if source.startswith("#!"):
        try:
            nl = source.index("\n") + 1
        except ValueError:
            return source + "\n" + block
        return source[:nl] + block + "\n" + source[nl:]
    if source.startswith("\n"):
        return block + source
    return block + "\n" + source


# --- WASM micropip bootstrap injection --------------------------------------


_BOOTSTRAP_SENTINEL = "_marimo_book_micropip_done"


def inject_micropip_bootstrap(source: str, packages: Sequence[str]) -> str:
    """Insert a top-level ``micropip.install`` cell + thread it as a dependency.

    For WASM-mode rendering: marimo's islands JS bundle auto-loads
    Pyodide-bundled packages via ``loadPackagesFromImports`` but has
    no codepath to install pure-Python PyPI-only deps (e.g.
    ``nltools``, ``dartbrains-tools``). We ship the install call
    inside cell code instead.

    **Why a separate cell, not a prepend-into-existing.** An earlier
    iteration of this transform prepended ``await micropip.install``
    directly into each ``@app.cell`` that had imports, converting
    sync cells to ``async def`` along the way. That broke real
    notebooks: a cell whose existing body did
    ``_ROOT = next(...)`` for a ``Path.cwd()`` walk would
    sometimes raise ``StopIteration`` from the staged tempdir, the
    cell would abort *before* its return statement, and downstream
    cells failed with ``Name 'mo' is not defined`` because marimo
    only collects exported variables from a cell that returns
    successfully.

    The current transform is non-destructive: it inserts a new
    ``@app.cell`` after ``app = marimo.App(...)`` whose only job is
    to ``await micropip.install([...])`` and define a sentinel
    ``_marimo_book_micropip_done = True``. Then it adds that
    sentinel as a parameter to every existing ``@app.cell`` (and
    ``@app.function``-style decorators are left alone). Marimo's
    dataflow analyzer treats the parameter as a dependency, so the
    bootstrap cell runs strictly before every other cell — without
    rewriting any user cell body or changing any existing function
    signature except by appending one parameter.

    Pyodide's ``micropip`` filters out packages already in
    ``sys.modules``, so bundled deps no-op. The injected install is
    wrapped in ``try/except ImportError`` so build-time CPython
    execution (where ``micropip`` doesn't exist) falls through.
    Marimo's CPython shim emits one informational
    ``"['…'] was not installed: micropip is only available in WASM
    notebooks."`` per build; expected and harmless.

    Comments inside the original ``.py`` survive — only the new cell
    is added and existing function signatures get one extra
    parameter; ``ast.unparse`` runs over the whole tree, so cell
    bodies are reformatted but their semantics are preserved.

    Returns ``source`` unchanged when ``packages`` is empty, when no
    ``@app.cell`` is found, or on syntax error.
    """
    if not packages:
        return source
    # Idempotency: skip if the source already carries our sentinel.
    # Otherwise re-running the transform (e.g. on an already-staged copy)
    # would append the parameter to every cell signature N times.
    if _BOOTSTRAP_SENTINEL in source:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    # Notebooks using ``with app.setup:`` aren't supported by this
    # transform: marimo runs the setup block before *any* ``@app.cell``,
    # so making cells depend on our sentinel doesn't get the install in
    # before the setup block's own third-party imports run. ``await`` is
    # also invalid at module-level Python, so we can't inject the install
    # into the setup block's body either. Caller can detect this case via
    # :func:`has_app_setup_block` and emit a build-time warning.
    if has_app_setup_block(tree):
        return source

    cell_nodes = [
        n
        for n in tree.body
        if isinstance(n, ast.FunctionDef | ast.AsyncFunctionDef) and _is_app_cell_decorated(n)
    ]
    if not cell_nodes:
        return source

    insert_idx = _find_app_assignment_index(tree)
    if insert_idx is None:
        return source

    # Add the sentinel parameter to every existing @app.cell. Marimo's
    # static analyzer reads parameter names as the cell's input
    # variables, so this makes every cell depend on the bootstrap.
    for cell in cell_nodes:
        existing = {a.arg for a in cell.args.args}
        if _BOOTSTRAP_SENTINEL not in existing:
            cell.args.args.append(ast.arg(arg=_BOOTSTRAP_SENTINEL, annotation=None))

    bootstrap_src = (
        "@app.cell(hide_code=True)\n"
        "async def _():\n"
        "    try:\n"
        "        import micropip\n"
        f"        await micropip.install({list(packages)!r})\n"
        "    except ImportError:\n"
        "        pass\n"
        f"    {_BOOTSTRAP_SENTINEL} = True\n"
        f"    return ({_BOOTSTRAP_SENTINEL},)\n"
    )
    bootstrap_nodes = ast.parse(bootstrap_src).body
    tree.body[insert_idx:insert_idx] = bootstrap_nodes

    ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def _is_app_cell_decorated(node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    """Whether ``node`` carries ``@app.cell`` or ``@app.cell(...)``."""
    for dec in node.decorator_list:
        target = dec.func if isinstance(dec, ast.Call) else dec
        if (
            isinstance(target, ast.Attribute)
            and isinstance(target.value, ast.Name)
            and target.value.id == "app"
            and target.attr == "cell"
        ):
            return True
    return False


def has_app_setup_block(source_or_tree: str | ast.Module) -> bool:
    """Whether the notebook uses marimo's ``with app.setup:`` construct.

    Marimo's setup block runs at module-import time before any
    ``@app.cell``; it's the user's escape hatch for "imports + globals
    every cell needs." Our sentinel-parameter approach can't inject a
    micropip install before it runs (see comment in
    :func:`inject_micropip_bootstrap`). Callers should fall back to a
    build-time warning for notebooks that hit this path.
    """
    tree = ast.parse(source_or_tree) if isinstance(source_or_tree, str) else source_or_tree
    for node in ast.walk(tree):
        if not isinstance(node, ast.With):
            continue
        for item in node.items:
            ctx = item.context_expr
            # Match either ``app.setup`` (attribute) or ``app.setup(...)`` (call).
            target = ctx.func if isinstance(ctx, ast.Call) else ctx
            if (
                isinstance(target, ast.Attribute)
                and isinstance(target.value, ast.Name)
                and target.value.id == "app"
                and target.attr == "setup"
            ):
                return True
    return False


def _find_app_assignment_index(tree: ast.Module) -> int | None:
    """Return the index of the statement *after* ``app = marimo.App(...)``.

    The bootstrap cell goes immediately after the ``app =`` line so
    its ``@app.cell`` decorator binds to the right object. Returns
    ``None`` when no such assignment is found (a notebook that
    doesn't define ``app`` isn't a marimo notebook in any meaningful
    sense, so we skip injection).
    """
    for i, node in enumerate(tree.body):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "app":
                    return i + 1
    return None
