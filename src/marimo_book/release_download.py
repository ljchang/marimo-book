"""Client-hydrated "download the latest release" component.

A book page emits a small placeholder ``<div data-mb-release-download …>``;
the bundled ``marimo_book.js`` finds it at page load, fetches
``api.github.com/repos/<owner>/<repo>/releases/latest`` in the browser, and
renders an OS-detecting set of download cards. Nothing happens at build time
(the build stays hermetic and offline-safe), and the data is always the
current latest release without rebuilding the site.

Two ways to place the component:

- **Python (marimo / sugar).** In a notebook cell::

      import marimo as mo
      from marimo_book import release_download

      release_download("cosanlab/pyfeat-live", app_name="Py-feat Live")

  ``release_download`` returns an ``mo.Html`` when marimo is importable
  (so the cell renders it directly), else the raw HTML string.

- **Raw HTML.** Drop the placeholder into any Markdown page or an
  ``mo.Html(...)`` cell::

      <div data-mb-release-download data-repo="cosanlab/pyfeat-live"></div>

A ``<noscript>`` fallback link to the GitHub releases page is always
embedded, so the component degrades to a working link with JS disabled and
is crawlable for SEO.
"""

from __future__ import annotations

import html
import json
from urllib.parse import urlparse

# Default platform matchers. Each entry maps a human label to a case-
# insensitive substring matched against release-asset filenames. Tuned for
# the common Tauri / desktop-app naming conventions; pass ``platforms=`` to
# override. Platforms whose asset is absent in a given release are simply
# not rendered (so a macOS-only release shows a single card).
DEFAULT_PLATFORMS: list[dict[str, str]] = [
    {"key": "mac-arm", "label": "macOS (Apple Silicon)", "match": "aarch64.dmg"},
    {"key": "mac-intel", "label": "macOS (Intel)", "match": "x64.dmg"},
    {"key": "windows", "label": "Windows", "match": ".msi"},
    {"key": "linux", "label": "Linux (AppImage)", "match": ".appimage"},
]


def normalize_repo(repo: str) -> str:
    """Return ``owner/name`` from either that shorthand or a GitHub URL.

    Accepts ``"owner/name"``, ``"https://github.com/owner/name"`` (any case),
    ``"github.com/owner/name(.git)"``. Raises ``ValueError`` on a non-github
    host, an embedded scheme, or anything that doesn't yield two path
    segments — so a typo fails loudly at config time rather than silently
    producing a wrong API URL.
    """
    repo = repo.strip()
    is_url = "://" in repo or repo.lower().startswith("github.com/")
    if is_url:
        parsed = urlparse(repo if "://" in repo else f"https://{repo}")
        host = parsed.netloc.lower()
        if host not in ("github.com", "www.github.com"):
            raise ValueError(f"release_download: only github.com URLs are supported, got {repo!r}")
        parts = [p for p in parsed.path.split("/") if p]
    else:
        parts = [p for p in repo.split("/") if p]
        if any(":" in p for p in parts):  # a scheme leaked into the shorthand
            raise ValueError(f"release_download: could not parse owner/repo from {repo!r}")
    if len(parts) < 2:
        raise ValueError(
            f"release_download: could not parse owner/repo from {repo!r} "
            "(expected 'owner/name' or a github.com URL)"
        )
    return f"{parts[0]}/{parts[1].removesuffix('.git')}"


def render_release_download_html(
    repo: str,
    *,
    platforms: list[dict[str, str]] | None = None,
    app_name: str | None = None,
) -> str:
    """Build the placeholder HTML for the release-download component.

    Pure function (no marimo dependency) so it's unit-testable. ``repo`` is
    ``owner/name`` or a GitHub URL; ``platforms`` overrides
    :data:`DEFAULT_PLATFORMS`; ``app_name`` is used in card aria-labels
    (defaults to the repo name).
    """
    owner_repo = normalize_repo(repo)
    label = app_name or owner_repo.split("/")[1]
    plats = platforms if platforms is not None else DEFAULT_PLATFORMS

    # JSON lives in a single-quoted attribute; html-escape so embedded
    # double quotes / ampersands survive. The browser un-escapes when the
    # hydrator reads the attribute, handing the JS clean JSON.
    platforms_attr = html.escape(json.dumps(plats), quote=True)
    repo_attr = html.escape(owner_repo, quote=True)
    name_attr = html.escape(label, quote=True)
    releases_url = f"https://github.com/{owner_repo}/releases/latest"

    return (
        '<div class="marimo-book-release-download" data-mb-release-download '
        f'data-repo="{repo_attr}" data-app-name="{name_attr}" '
        f"data-platforms='{platforms_attr}'>"
        '<div class="marimo-book-release-download__loading">'
        "Loading the latest release…</div>"
        f'<noscript><a href="{releases_url}" target="_blank" rel="noopener">'
        f"Download the latest {html.escape(label)} release on GitHub</a>"
        "</noscript>"
        "</div>"
    )


def release_download(
    repo: str,
    *,
    platforms: list[dict[str, str]] | None = None,
    app_name: str | None = None,
):
    """Return the component, ready to render in a marimo cell.

    Wraps :func:`render_release_download_html` in ``mo.Html`` when marimo is
    importable; otherwise returns the raw HTML string (still usable inside
    ``mo.Html(...)`` or a Markdown raw-HTML block).
    """
    markup = render_release_download_html(repo, platforms=platforms, app_name=app_name)
    try:
        import marimo as mo
    except ImportError:
        return markup
    return mo.Html(markup)
