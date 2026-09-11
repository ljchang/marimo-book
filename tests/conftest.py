"""Shared pytest configuration."""

from __future__ import annotations

from pathlib import Path

import pytest

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _offline_pyodide_lock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Point marimo's Pyodide lockfile resolver at a tiny local fixture.

    ``wasm_install_packages`` filters Pyodide-bundled packages out of the
    WASM micropip install list via ``marimo._pyodide.pyodide_constraints``,
    which otherwise fetches ``pyodide-lock.json`` from wasm.marimo.app. The
    fixture lists numpy/pandas/matplotlib/scipy as bundled so tests are
    deterministic and never touch the network.
    """
    monkeypatch.setenv("MARIMO_PYODIDE_LOCK_FILE", str(FIXTURES / "pyodide-lock.json"))
