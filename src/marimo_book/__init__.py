"""marimo-book: build static sites from marimo notebooks and Markdown."""

from importlib.metadata import PackageNotFoundError, version as _pkg_version

try:
    __version__ = _pkg_version("marimo-book")
except PackageNotFoundError:
    # Editable install on an untagged commit before the build hook has
    # materialised _version.py. Fall back to a sentinel.
    __version__ = "0.0.0+unknown"
