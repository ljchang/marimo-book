"""Tests for the PEP 723 inline-script-metadata transform.

Covers extraction (AST walk + stdlib filter), distribution mapping
(marimo's table + overrides + fallback), end-to-end derivation
(extras precedence, env pinning), and block round-trip
(insert/preserve/replace).
"""

from __future__ import annotations

from marimo_book.transforms.pep723 import (
    derive_dependencies,
    extract_imports,
    has_pep723_block,
    inject_micropip_bootstrap,
    map_to_distributions,
    read_existing_dependencies,
    write_pep723_block,
)

# --- extract_imports --------------------------------------------------------


def test_extract_imports_filters_stdlib() -> None:
    src = "import os\nimport sys\nimport json\nfrom pathlib import Path\nimport requests\n"
    assert extract_imports(src) == {"requests"}


def test_extract_imports_filters_marimo() -> None:
    src = "import marimo as mo\nimport numpy\n"
    assert extract_imports(src) == {"numpy"}


def test_extract_imports_collapses_dotted() -> None:
    src = "from sklearn.linear_model import LinearRegression\nimport matplotlib.pyplot as plt\n"
    assert extract_imports(src) == {"sklearn", "matplotlib"}


def test_extract_imports_skips_relative_imports() -> None:
    src = "from . import sibling\nfrom .util import helper\nimport requests\n"
    assert extract_imports(src) == {"requests"}


def test_extract_imports_collects_conditional() -> None:
    """PEP 723 has no conditional deps; treat any reachable import as required."""
    src = """
try:
    import numpy
except ImportError:
    import math
if False:
    import pandas
"""
    # ``math`` is stdlib (filtered); ``numpy`` and ``pandas`` survive.
    assert extract_imports(src) == {"numpy", "pandas"}


def test_extract_imports_handles_syntax_error() -> None:
    """Malformed source returns an empty set, not an exception."""
    assert extract_imports("def : bad\n") == set()


def test_extract_imports_empty_source() -> None:
    assert extract_imports("") == set()


# --- map_to_distributions ---------------------------------------------------


def test_map_to_distributions_known_mappings() -> None:
    """Canonical import-name → distribution-name remappings from marimo's table."""
    out = map_to_distributions({"PIL", "cv2", "sklearn", "yaml", "bs4"})
    assert "Pillow" in out
    assert "opencv-python" in out
    assert "scikit-learn" in out
    assert "PyYAML" in out
    assert "beautifulsoup4" in out


def test_map_to_distributions_fallback_underscores() -> None:
    """Names absent from marimo's table fall back to ``_``→``-`` normalisation."""
    out = map_to_distributions({"my_package", "other_thing"})
    assert "my-package" in out
    assert "other-thing" in out


def test_map_to_distributions_user_overrides_win() -> None:
    """Caller-supplied overrides beat both the table and the fallback."""
    out = map_to_distributions(
        {"PIL", "internal_thing"},
        overrides={"PIL": "my-custom-pil", "internal_thing": "internal-pkg"},
    )
    assert out == ["internal-pkg", "my-custom-pil"]


def test_map_to_distributions_dartbrains_imports() -> None:
    """The actual broken-WASM-page case: scientific-stack imports resolve correctly.

    None of these are in marimo's mapping table; all should fall through
    to the ``_``→``-`` fallback (which leaves them unchanged because they
    have no underscores to begin with).
    """
    out = map_to_distributions({"numpy", "pandas", "nilearn", "nltools", "nibabel"})
    assert out == ["nibabel", "nilearn", "nltools", "numpy", "pandas"]


# --- derive_dependencies ----------------------------------------------------


def test_derive_dependencies_extras_override_detected() -> None:
    """An extra naming the same distribution as a detected import wins.

    Use case: detect ``import nltools`` (unpinned), but caller supplied
    ``nltools>=0.5`` in ``dependencies.extras`` — keep the version
    specifier, drop the unpinned duplicate.
    """
    out = derive_dependencies("import nltools\nimport numpy\n", extras=["nltools>=0.5"])
    assert out == ["nltools>=0.5", "numpy"]


def test_derive_dependencies_env_pinning_falls_back() -> None:
    """``pin='env'`` only pins distributions actually installed in the env.

    ``tomlkit`` IS installed (it's a marimo transitive dep), so it gets
    pinned. ``definitely-not-installed-pkg`` is NOT in the env and
    passes through unpinned.
    """
    src = "import tomlkit\nimport definitely_not_installed_pkg\n"
    out = derive_dependencies(src, pin="env")
    pinned = [d for d in out if d.startswith("tomlkit==")]
    unpinned = [d for d in out if d == "definitely-not-installed-pkg"]
    assert len(pinned) == 1
    assert len(unpinned) == 1


def test_derive_dependencies_alphabetical_case_insensitive() -> None:
    """Output is sorted by canonical (lowercased) distribution name."""
    out = derive_dependencies("import PIL\nimport numpy\nimport bs4\n")
    # canonical: ['beautifulsoup4', 'numpy', 'pillow']
    assert [d.lower() for d in out] == sorted(d.lower() for d in out)


# --- block writer round-trip ------------------------------------------------


def test_write_pep723_block_inserts_at_top() -> None:
    """No existing block → block is prepended (with a blank-line separator)."""
    src = "import numpy as np\n"
    out = write_pep723_block(src, ["numpy"], requires_python=">=3.11")
    assert out.startswith("# /// script\n")
    assert '# requires-python = ">=3.11"' in out
    assert "# ///\n" in out
    assert out.endswith("import numpy as np\n")


def test_write_pep723_block_preserves_shebang() -> None:
    """Shebang stays on line 1; block is inserted after it."""
    src = "#!/usr/bin/env python\nimport numpy\n"
    out = write_pep723_block(src, ["numpy"])
    lines = out.splitlines()
    assert lines[0] == "#!/usr/bin/env python"
    assert lines[1] == "# /// script"


def test_write_pep723_block_replaces_in_place() -> None:
    """An existing block + new deps merge by canonical name (preserve_existing=True)."""
    src = """# /// script
# dependencies = [
#     "numpy",
# ]
# ///

import numpy as np
import pandas as pd
"""
    out = write_pep723_block(src, ["numpy", "pandas"])
    deps = read_existing_dependencies(out)
    assert deps == ["numpy", "pandas"]


def test_write_pep723_block_preserves_tool_uv_section() -> None:
    """Existing ``[tool.uv]`` (and other top-level tables) survive a merge."""
    src = """# /// script
# requires-python = ">=3.11"
# dependencies = [
#     "numpy",
# ]
#
# [tool.uv]
# extra-index-url = ["https://example/"]
# ///

import numpy
"""
    out = write_pep723_block(src, ["pandas"])
    assert "[tool.uv]" in out
    assert 'extra-index-url = ["https://example/"]' in out
    assert 'requires-python = ">=3.11"' in out


def test_write_pep723_block_overwrite_drops_other_keys() -> None:
    """``preserve_existing=False`` replaces the block wholesale."""
    src = """# /// script
# requires-python = ">=3.10"
# dependencies = ["legacy-pkg"]
# [tool.uv]
# extra-index-url = ["https://example/"]
# ///

import numpy
"""
    out = write_pep723_block(src, ["numpy"], requires_python=">=3.11", preserve_existing=False)
    assert "legacy-pkg" not in out
    assert "tool.uv" not in out
    assert 'requires-python = ">=3.11"' in out


def test_write_pep723_block_idempotent() -> None:
    """Running the writer twice yields identical output (no drift)."""
    src = "import numpy\nimport pandas\n"
    once = write_pep723_block(src, ["numpy", "pandas"], requires_python=">=3.11")
    twice = write_pep723_block(once, ["numpy", "pandas"], requires_python=">=3.11")
    assert once == twice


def test_write_pep723_block_dependencies_sorted() -> None:
    """Generated block lists dependencies in canonical-name order."""
    src = "import numpy\nimport bs4\nimport PIL\n"
    out = write_pep723_block(src, derive_dependencies(src), requires_python=">=3.11")
    parsed = read_existing_dependencies(out) or []
    assert parsed == sorted(parsed, key=str.lower)


def test_write_pep723_block_emits_multiline_array() -> None:
    """Each dependency sits on its own line (canonical PEP 723 layout)."""
    src = "import numpy\nimport pandas\n"
    out = write_pep723_block(src, ["numpy", "pandas"])
    assert '# dependencies = [\n#     "numpy",\n#     "pandas",\n# ]' in out


# --- has_pep723_block / read_existing_dependencies --------------------------


def test_has_pep723_block_detects_block() -> None:
    assert has_pep723_block("# /// script\n# dependencies = []\n# ///\n") is True
    assert has_pep723_block("import numpy\n") is False


def test_read_existing_dependencies_returns_none_when_absent() -> None:
    assert read_existing_dependencies("import numpy\n") is None


def test_read_existing_dependencies_empty_block() -> None:
    """A block with no ``dependencies`` key returns the empty list, not None."""
    src = '# /// script\n# requires-python = ">=3.11"\n# ///\n'
    assert read_existing_dependencies(src) == []


# --- inject_micropip_bootstrap ----------------------------------------------


_NOTEBOOK_SRC = """import marimo
app = marimo.App()


@app.cell(hide_code=True)
def _():
    import marimo as mo
    return (mo,)


@app.cell
def _(mo):
    import nltools
    return (nltools,)
"""


def test_inject_bootstrap_inserts_one_async_cell() -> None:
    """A single new ``@app.cell`` carries the install; existing cells stay sync.

    An earlier prepend-into-existing design converted user cells to
    ``async def`` and broke real notebooks (cells whose body raised
    before their return statement stopped exporting variables, leading
    to ``Name 'mo' is not defined`` cascades downstream). The current
    design adds ONE new async cell at the top and leaves user cell
    bodies untouched — only their parameter lists gain a sentinel
    (verified by the next test).
    """
    out = inject_micropip_bootstrap(_NOTEBOOK_SRC, ["nltools", "numpy"])
    assert out.count("async def _") == 1
    assert out.count("await micropip.install(['nltools', 'numpy'])") == 1
    # User cell bodies survive without modification.
    assert "import marimo as mo" in out
    assert "import nltools" in out


def test_inject_bootstrap_threads_sentinel_to_every_cell() -> None:
    """Every existing ``@app.cell`` gains the sentinel parameter.

    Marimo's static analyzer reads parameter names as the cell's input
    variables. Adding the sentinel makes every existing cell depend on
    the bootstrap, so marimo's dataflow scheduler runs the bootstrap
    before any other cell — even if the source-order-first cell only
    does ``mo.md(...)`` and would otherwise be runtime-second.
    """
    out = inject_micropip_bootstrap(_NOTEBOOK_SRC, ["nltools"])
    sentinel = "_marimo_book_micropip_done"
    # Two original cells; both should now have the sentinel as a parameter.
    # The bootstrap cell defines + returns it (so it appears in `return (...)`).
    assert out.count(f"def _({sentinel})") + out.count(f", {sentinel})") == 2
    # The bootstrap cell's body sets and returns the sentinel.
    assert f"{sentinel} = True" in out
    assert f"return ({sentinel},)" in out


def test_inject_bootstrap_no_double_threading_on_re_run() -> None:
    """Running the injector twice doesn't add the sentinel parameter twice."""
    once = inject_micropip_bootstrap(_NOTEBOOK_SRC, ["nltools"])
    twice = inject_micropip_bootstrap(once, ["nltools"])
    # The sentinel parameter should appear exactly the same number of times,
    # not be duplicated. Count occurrences in the args (after a comma-or-paren).
    sentinel_in_params = twice.count("_marimo_book_micropip_done)") + twice.count(
        "_marimo_book_micropip_done,"
    )
    once_count = once.count("_marimo_book_micropip_done)") + once.count(
        "_marimo_book_micropip_done,"
    )
    assert sentinel_in_params == once_count


def test_inject_bootstrap_handles_notebook_without_app_assignment() -> None:
    """A file without an ``app = marimo.App(...)`` assignment is unchanged.

    Not a marimo notebook in any meaningful sense; we skip rather than
    insert a bootstrap that would have no app to decorate.
    """
    src = "@app.cell\ndef _():\n    import nltools\n    return (nltools,)\n"
    assert inject_micropip_bootstrap(src, ["nltools"]) == src


def test_inject_bootstrap_wraps_in_try_except() -> None:
    """Build-time CPython lacks micropip; the wrapper must swallow ImportError.

    Without this, the build crashes when MarimoIslandGenerator.build()
    runs the cell locally before the browser ever sees it.
    """
    out = inject_micropip_bootstrap(_NOTEBOOK_SRC, ["nltools"])
    assert "try:" in out
    assert "except ImportError:" in out


def test_inject_bootstrap_preserves_decorator_kwargs() -> None:
    """The ``@app.cell(hide_code=True)`` form survives the AST round-trip."""
    out = inject_micropip_bootstrap(_NOTEBOOK_SRC, ["pkg"])
    assert "@app.cell(hide_code=True)" in out


def test_inject_bootstrap_handles_already_async_user_cell() -> None:
    """User cells already authored as ``async def`` keep their signature.

    The new design adds one separate bootstrap cell + a sentinel
    parameter to existing cells. An async user cell stays async, gains
    the sentinel, and its body is untouched.
    """
    src = """import marimo

app = marimo.App()


@app.cell
async def _():
    import some_pkg

    await some_async_thing()
    return
"""
    out = inject_micropip_bootstrap(src, ["pkg"])
    # Two ``async def _`` lines: the new bootstrap + the original async cell.
    assert out.count("async def _") == 2
    # User cell's body stays — the await line is preserved.
    assert "await some_async_thing()" in out


def test_inject_bootstrap_empty_packages_no_op() -> None:
    """Empty package list returns source unchanged."""
    assert inject_micropip_bootstrap(_NOTEBOOK_SRC, []) == _NOTEBOOK_SRC


def test_inject_bootstrap_no_app_cell_no_op() -> None:
    """A file without ``@app.cell`` decorators is returned unchanged.

    Possible cases: a marimo notebook stub still being authored, or a
    plain Python script accidentally fed to this function.
    """
    src = "import marimo\napp = marimo.App()\n"
    assert inject_micropip_bootstrap(src, ["pkg"]) == src


def test_inject_bootstrap_syntax_error_no_op() -> None:
    """Malformed source returns unchanged rather than crashing the build."""
    src = "def : not python\n"
    assert inject_micropip_bootstrap(src, ["pkg"]) == src


def test_inject_bootstrap_runs_before_user_cells_at_runtime() -> None:
    """The bootstrap cell appears before any user ``@app.cell`` in source.

    Marimo's dataflow scheduler doesn't follow source order; what
    actually orders the bootstrap first at *runtime* is the sentinel
    parameter on every other cell. Source order matters only for
    decorator binding (the new ``@app.cell`` needs to bind to ``app``,
    so it must come after the ``app = marimo.App(...)`` assignment).
    Both invariants are checked here.
    """
    out = inject_micropip_bootstrap(_NOTEBOOK_SRC, ["nltools"])
    app_pos = out.index("app = marimo.App()")
    bootstrap_pos = out.index("await micropip.install")
    first_user_cell_pos = out.index("def _(_marimo_book_micropip_done):")
    # Bootstrap is between `app = ...` and the first existing cell.
    assert app_pos < bootstrap_pos < first_user_cell_pos
