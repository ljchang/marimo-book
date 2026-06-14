"""The client-hydrated release-download component."""

import json
import re
from pathlib import Path

import pytest

from marimo_book.release_download import (
    DEFAULT_PLATFORMS,
    normalize_repo,
    render_release_download_html,
)

ASSETS = Path(__file__).resolve().parents[1] / "src" / "marimo_book" / "assets"


# --- repo normalization ------------------------------------------------------


@pytest.mark.parametrize(
    "value,expected",
    [
        ("cosanlab/pyfeat-live", "cosanlab/pyfeat-live"),
        ("https://github.com/cosanlab/pyfeat-live", "cosanlab/pyfeat-live"),
        ("https://github.com/cosanlab/pyfeat-live.git", "cosanlab/pyfeat-live"),
        ("github.com/cosanlab/pyfeat-live", "cosanlab/pyfeat-live"),
        ("https://github.com/cosanlab/pyfeat-live/releases", "cosanlab/pyfeat-live"),
    ],
)
def test_normalize_repo(value, expected):
    assert normalize_repo(value) == expected


def test_normalize_repo_rejects_garbage():
    with pytest.raises(ValueError):
        normalize_repo("not-a-repo")


# --- HTML builder ------------------------------------------------------------


def test_html_has_hydration_hook_and_repo():
    out = render_release_download_html("cosanlab/pyfeat-live")
    assert "data-mb-release-download" in out
    assert 'data-repo="cosanlab/pyfeat-live"' in out
    assert "marimo-book-release-download" in out


def test_html_accepts_github_url():
    out = render_release_download_html("https://github.com/cosanlab/pyfeat-live")
    assert 'data-repo="cosanlab/pyfeat-live"' in out


def test_html_embeds_default_platforms_as_json():
    out = render_release_download_html("o/r")
    m = re.search(r"data-platforms='([^']*)'", out)
    assert m, "data-platforms attribute missing"
    # The attribute is html-escaped; un-escape the way a browser would.
    raw = m.group(1).replace("&quot;", '"').replace("&#x27;", "'").replace("&amp;", "&")
    plats = json.loads(raw)
    assert plats == DEFAULT_PLATFORMS


def test_html_custom_platforms_override_defaults():
    custom = [{"key": "mac", "label": "macOS", "match": ".dmg"}]
    out = render_release_download_html("o/r", platforms=custom)
    m = re.search(r"data-platforms='([^']*)'", out)
    raw = m.group(1).replace("&quot;", '"')
    assert json.loads(raw) == custom


def test_html_app_name_defaults_to_repo_name():
    out = render_release_download_html("cosanlab/pyfeat-live")
    assert 'data-app-name="pyfeat-live"' in out


def test_html_app_name_override():
    out = render_release_download_html("cosanlab/pyfeat-live", app_name="Py-feat Live")
    assert 'data-app-name="Py-feat Live"' in out


def test_html_noscript_fallback_links_to_releases():
    out = render_release_download_html("cosanlab/pyfeat-live")
    assert "<noscript>" in out
    assert "https://github.com/cosanlab/pyfeat-live/releases/latest" in out


# --- shipped assets carry the runtime ----------------------------------------


def test_bundled_js_contains_hydrator():
    js = (ASSETS / "marimo_book.js").read_text(encoding="utf-8")
    assert "hydrateReleaseDownloads" in js
    # It must be wired into the boot chain or it never runs.
    assert "hydrateReleaseDownloads(scope)" in js
    # Idempotency guard so Material instant-nav re-boots don't double-render.
    assert "data-mb-rd-init" in js


def test_bundled_css_styles_the_component():
    css = (ASSETS / "extra.css").read_text(encoding="utf-8")
    assert ".marimo-book-release-download" in css
