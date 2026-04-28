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


def inject_micropip_bootstrap(source: str, packages: Sequence[str]) -> str:
    """Prepend ``await micropip.install([...])`` to the first ``@app.cell``.

    For WASM-mode rendering: marimo's islands JS bundle auto-loads
    Pyodide-bundled packages via ``loadPackagesFromImports`` but has no
    codepath to install pure-Python PyPI-only deps (e.g. ``nltools``).
    We ship the install call inside cell code instead. Pyodide's
    ``micropip`` filters out anything already present in
    ``sys.modules``, so passing the full :func:`derive_dependencies`
    output is safe — bundled packages no-op, non-bundled ones install.

    The injected block is wrapped in ``try/except ImportError`` so
    build-time CPython execution (where ``micropip`` doesn't exist)
    fails gracefully rather than crashing the build.

    Implementation: AST-walk to the first ``@app.cell``-decorated
    function, prepend the bootstrap statements to its body, convert
    ``def`` to ``async def`` if needed, and unparse. Comments inside
    cells do not survive ``ast.unparse``; that's acceptable here
    because this transform only runs on the staged tempdir copy that
    marimo reads at build time, never on the user's source.

    Returns ``source`` unchanged when ``packages`` is empty, when no
    ``@app.cell`` decorator is found, or on syntax error.
    """
    if not packages:
        return source
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return source

    transformer = _BootstrapInjector(list(packages))
    new_tree = transformer.visit(tree)
    if not transformer.injected:
        return source
    ast.fix_missing_locations(new_tree)
    return ast.unparse(new_tree) + "\n"


class _BootstrapInjector(ast.NodeTransformer):
    """Find the first ``@app.cell`` function and prepend a micropip-install."""

    def __init__(self, packages: list[str]) -> None:
        self.packages = packages
        self.injected = False

    def visit_FunctionDef(self, node: ast.FunctionDef) -> ast.AST:
        if self.injected or not _is_app_cell_decorated(node):
            return node
        new_body = _bootstrap_statements(self.packages) + list(node.body)
        new_node = ast.AsyncFunctionDef(
            name=node.name,
            args=node.args,
            body=new_body,
            decorator_list=node.decorator_list,
            returns=node.returns,
            type_comment=node.type_comment,
        )
        ast.copy_location(new_node, node)
        self.injected = True
        return new_node

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> ast.AST:
        if self.injected or not _is_app_cell_decorated(node):
            return node
        node.body = _bootstrap_statements(self.packages) + list(node.body)
        self.injected = True
        return node


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


def _bootstrap_statements(packages: list[str]) -> list[ast.stmt]:
    """Parse the bootstrap source into AST statements ready to splice into a body."""
    pkg_repr = repr(list(packages))
    src = (
        "try:\n"
        "    import micropip\n"
        f"    await micropip.install({pkg_repr})\n"
        "except ImportError:\n"
        "    pass\n"
    )
    return ast.parse(src).body
