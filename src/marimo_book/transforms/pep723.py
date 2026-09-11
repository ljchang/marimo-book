"""Notebook dependency analysis: PEP 723 generation + WASM micropip bootstrap.

Two jobs:

1. **PEP 723 generation** — walk a notebook's AST, collect its imports,
   map module names to PyPI distributions, and write a
   ``# /// script`` inline-metadata block (the format read by ``uv run``,
   ``marimo --sandbox``, molab, and any other PEP-723-aware tool).
   Build-time staging writes the block into a sibling copy of the
   notebook; ``marimo-book sync-deps`` writes it back into the source.

2. **WASM micropip bootstrap** — for pages rendered through
   ``MarimoIslandGenerator`` (WASM mode), provide the pieces of an
   islands JSON payload (marimo >= 0.24, marimo-team/marimo#9987) that
   installs pure-Python PyPI-only deps before any user cell runs:
   :func:`micropip_bootstrap_code` is the body of an extra, DOM-less
   payload cell that ``await micropip.install([...])``s the derived
   dependency list and defines a sentinel variable;
   :func:`thread_bootstrap_sentinel` prefixes every user cell's payload
   code with a bare reference to that sentinel, so marimo's dataflow
   analyzer schedules the bootstrap strictly first. The islands JS
   bundle auto-loads Pyodide-bundled packages via
   ``loadPackagesFromImports`` but only honours a PEP 723 block at column
   zero of the notebook file it synthesizes from cell bodies — which it
   never carries over from the source — so without this the install
   never happens (see marimo-team/marimo#9778). The payload is assembled
   in :mod:`marimo_book.transforms.wasm`; the executed/staged notebook
   source is never touched for this.

Uses marimo's own internals so the mapping stays in sync with marimo:

- ``marimo._runtime.packages.module_name_to_pypi_name`` — the same
  mapping table marimo uses for its own micropip fallback resolution.
- ``marimo._utils.scripts.read_pyproject_from_script`` — the PEP 723
  parser.
- ``marimo._utils.scripts.wrap_script_metadata`` — adds ``# `` prefixes
  to TOML lines.
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


# --- WASM micropip bootstrap (islands JSON payload cell) ----------------------

BOOTSTRAP_SENTINEL = "marimo_book_micropip_done"
"""Variable the bootstrap cell defines and every user cell references.

Marimo's dataflow analyzer derives a cell's inputs from the names it
*reads*, so a bare ``marimo_book_micropip_done`` expression statement at
the top of a cell body makes that cell depend on — and run strictly
after — the cell that defines it. It must NOT start with an underscore:
marimo makes underscore-prefixed names cell-local, and the reference in
every other cell would raise ``NameError`` (verified in the browser).
"""

BOOTSTRAP_CELL_ID = "marimo-book-micropip-bootstrap"
"""``cellId`` of the payload-only bootstrap cell (no ``<marimo-island>`` anchor)."""


def micropip_bootstrap_code(packages: Sequence[str]) -> str:
    """Cell body that installs ``packages`` via micropip and defines the sentinel.

    Runs only in the browser (payload cells are never executed at build
    time), but stays wrapped in ``try/except ImportError`` so the same
    body is safe if it ever lands in a CPython context. Pyodide's
    micropip skips anything already importable, so passing the full
    derived dependency list is safe: bundled packages no-op, PyPI-only
    pure-Python ones install. The ``await`` makes marimo's islands
    runtime wrap the cell as ``async def``.
    """
    return (
        "try:\n"
        "    import micropip\n"
        f"    await micropip.install({list(packages)!r})\n"
        "except ImportError:\n"
        "    pass\n"
        f"{BOOTSTRAP_SENTINEL} = True\n"
    )


def thread_bootstrap_sentinel(code: str) -> str:
    """Prefix a cell body with a bare reference to :data:`BOOTSTRAP_SENTINEL`.

    Idempotent, and a no-op for empty bodies (the islands runtime emits
    ``pass`` for those; nothing to order). The leading expression
    statement is invisible in the cell's output — marimo displays only
    the *last* expression — and never changes the names a cell defines.
    """
    if not code.strip() or BOOTSTRAP_SENTINEL in code:
        return code
    return f"{BOOTSTRAP_SENTINEL}\n{code}"
