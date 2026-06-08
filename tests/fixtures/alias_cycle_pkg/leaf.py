"""A submodule that imports its own top-level package by name."""

import alias_cycle_pkg  # noqa: F401


def thing() -> str:
    """Return a thing."""
    return "thing"
