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
    map_to_distributions,
    micropip_bootstrap_code,
    pyodide_bundled_packages,
    read_existing_dependencies,
    thread_bootstrap_sentinel,
    wasm_install_packages,
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


# --- WASM micropip bootstrap (payload cell helpers) --------------------------


def test_bootstrap_code_installs_packages_and_always_binds_sentinel() -> None:
    """The payload cell body awaits the install and binds the sentinel last.

    ``await`` is what makes marimo's islands runtime wrap the synthesized
    cell as ``async def``. The sentinel must be bound even when the install
    raises: every user cell reads it, so an unbound sentinel would cancel
    the whole page — and the anchor-less bootstrap cell has no island to
    show a traceback in. Hence a catch-all that prints instead of raising.
    """
    code = micropip_bootstrap_code(["nltools", "numpy>=1.26"])
    assert "await micropip.install(['nltools', 'numpy>=1.26'])" in code
    assert code.rstrip().endswith("marimo_book_micropip_done = True")
    assert "except ImportError:" in code
    assert "except Exception as _exc:" in code
    # The sentinel assignment is at top level, after the try block.
    assert code.index("except Exception") < code.index("marimo_book_micropip_done = True")
    compile(code.replace("await ", ""), "<bootstrap>", "exec")


def test_thread_sentinel_prefixes_assignment() -> None:
    out = thread_bootstrap_sentinel("import nltools\nnltools.__version__")
    assert out.startswith("_ = marimo_book_micropip_done\n")
    # Body untouched below the prefix — including the last expression,
    # which is what marimo displays as the cell output.
    assert out.endswith("import nltools\nnltools.__version__")


def test_thread_sentinel_creates_dataflow_edge_without_a_def() -> None:
    """marimo must see the sentinel as a ref and ``_`` as cell-local (no def)."""
    from marimo._ast.compiler import compile_cell

    cell = compile_cell(thread_bootstrap_sentinel("x = 1"), cell_id="t")
    assert "marimo_book_micropip_done" in cell.refs
    assert "_" not in cell.defs


def test_thread_sentinel_idempotent() -> None:
    once = thread_bootstrap_sentinel("x = 1")
    assert thread_bootstrap_sentinel(once) == once


def test_thread_sentinel_leaves_statement_free_cells_alone() -> None:
    """Empty and comment-only bodies compile to no statements; the runtime
    emits ``pass`` for them and a prefix would become their (displayed)
    last expression."""
    assert thread_bootstrap_sentinel("") == ""
    assert thread_bootstrap_sentinel("   \n") == "   \n"
    assert thread_bootstrap_sentinel("# scratch\n") == "# scratch\n"


def test_thread_sentinel_mention_in_comment_still_prefixed() -> None:
    """Only the exact prefix counts as already-threaded; a cell that merely
    mentions the sentinel in a comment or string must still get the edge."""
    src = "# see marimo_book_micropip_done\nimport nltools"
    assert thread_bootstrap_sentinel(src) == "_ = marimo_book_micropip_done\n" + src


# --- wasm_install_packages ---------------------------------------------------


def test_bundled_packages_come_from_lockfile_fixture() -> None:
    bundled = pyodide_bundled_packages(None)
    assert bundled is not None
    assert {"numpy", "pandas"} <= bundled
    # ``-tests`` entries are excluded by marimo's resolver.
    assert "numpy-tests" not in bundled


def test_bundled_packages_unreadable_lockfile_returns_none(monkeypatch, tmp_path) -> None:
    """An unreadable lockfile must mean "don't filter", never "drop installs"."""
    monkeypatch.setenv("MARIMO_PYODIDE_LOCK_FILE", str(tmp_path / "missing.json"))
    assert pyodide_bundled_packages(None) is None


def test_bundled_packages_cached_on_disk_per_pyodide_version(monkeypatch, tmp_path) -> None:
    """Without the env override the list is read from / written to the cache dir."""
    from marimo._pyodide.pyodide_constraints import PYODIDE_VERSION

    cache = tmp_path / "cache"
    cache.mkdir()
    (cache / f"pyodide-bundled-{PYODIDE_VERSION}.json").write_text('["onlythis"]')
    monkeypatch.delenv("MARIMO_PYODIDE_LOCK_FILE")
    assert pyodide_bundled_packages(cache) == frozenset({"onlythis"})


_WASM_SRC = """# /// script
# dependencies = ["pandas", "pyarrow>=15"]
# ///
import marimo
app = marimo.App()


@app.cell
def _():
    import numpy
    import pandas as pd
    import nltools
    return
"""


def test_wasm_install_packages_merges_block_and_drops_bundled() -> None:
    """Import-derived ∪ hand-written PEP 723 deps, minus Pyodide-bundled.

    ``pyarrow`` only appears in the notebook's own block (no import), so it
    must survive; numpy/pandas are bundled in the fixture lock and go.
    """
    pkgs = wasm_install_packages(_WASM_SRC)
    assert set(pkgs) == {"nltools", "pyarrow>=15"}


def test_wasm_install_packages_hand_written_pin_wins() -> None:
    """A pin in the notebook's own block beats the unpinned import-derived
    name — the same precedence ``write_pep723_block`` gives the staged
    manifest, so sandbox/molab and the browser install the same thing."""
    src = _WASM_SRC.replace('"pandas", "pyarrow>=15"', '"nltools==0.4.0", "pyarrow>=15"')
    pkgs = wasm_install_packages(src)
    assert "nltools==0.4.0" in pkgs
    assert "nltools" not in pkgs


def test_wasm_install_packages_without_lockfile_keeps_everything(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARIMO_PYODIDE_LOCK_FILE", str(tmp_path / "missing.json"))
    pkgs = wasm_install_packages(_WASM_SRC)
    assert {"numpy", "pandas", "nltools", "pyarrow>=15"} <= set(pkgs)
