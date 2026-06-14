"""marimo-book: build static sites from marimo notebooks and Markdown."""

from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version

from .release_download import release_download, render_release_download_html

try:
    __version__ = _pkg_version("marimo-book")
except PackageNotFoundError:
    # Editable install on an untagged commit before the build hook has
    # materialised _version.py. Fall back to a sentinel.
    __version__ = "0.0.0+unknown"

__all__ = ["release_download", "render_release_download_html", "__version__"]
