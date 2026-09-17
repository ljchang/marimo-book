"""The header repository link, and the icon it shares with the launch buttons.

`repo:` reaches Material as `repo_url`, which renders a source card in the
header carrying star and fork counts. extra.css hides that card, so
`mountHeaderRepoLink` in marimo_book.js mounts a plain icon link in its place,
reading the URL out of the hidden element.

The icon is the one place this costs something: the launch-button row is built
in Python and this link is built in JavaScript, with no build step between
them, so the octocat path exists twice. These tests hold the two copies
together and pin the behaviour the JS depends on -- chiefly that `repo_url`
keeps being set, since the link reads its href from what Material renders
for it.
"""

from __future__ import annotations

import re
from pathlib import Path

from marimo_book.config import Book
from marimo_book.launch_buttons import _ICON_GITHUB
from marimo_book.shell import _build_config

ASSETS = Path(__file__).resolve().parents[1] / "src" / "marimo_book" / "assets"
JS = (ASSETS / "marimo_book.js").read_text()
CSS = (ASSETS / "extra.css").read_text()


def _svg_path(markup: str) -> str:
    """The single `d` attribute in a one-path SVG."""
    paths = re.findall(r'\bd="([^"]+)"', markup)
    assert len(paths) == 1, f"expected one path, found {len(paths)}"
    return paths[0]


def _js_repo_icon() -> str:
    """REPO_ICON's value, reassembled from its concatenated JS string parts.

    The literals alternate between single and double quotes so each can hold
    the other kind verbatim -- the SVG markup is full of `"`. So match a whole
    literal of either flavour rather than any run between quote characters.
    """
    body = JS.split("const REPO_ICON =", 1)[1].split(";", 1)[0]
    parts = re.findall(r"'([^']*)'|\"([^\"]*)\"", body)
    return "".join(single or double for single, double in parts)


def test_the_octocat_path_is_identical_in_python_and_javascript():
    """The duplication is deliberate; drifting out of sync is not."""
    assert _svg_path(_js_repo_icon()) == _svg_path(_ICON_GITHUB)


def test_the_js_icon_carries_the_button_icon_class():
    # Without it the glyph has no size rule and renders at the SVG's
    # intrinsic dimensions, which is far larger than the header.
    assert 'class="marimo-book-button-icon"' in _js_repo_icon()


def test_repo_url_is_still_what_the_link_reads_its_href_from():
    cfg = _build_config(
        Book(title="T", toc=[], repo="https://github.com/o/r"),
        docs_dir=Path("docs"),
        site_dir=Path("site"),
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert cfg["repo_url"] == "https://github.com/o/r"


def test_no_repo_means_no_repo_url_and_so_no_link():
    cfg = _build_config(
        Book(title="T", toc=[]),
        docs_dir=Path("docs"),
        site_dir=Path("site"),
        nav=[],
        extra_css=[],
        extra_javascript=[],
    )
    assert "repo_url" not in cfg


def test_the_link_is_mounted_and_styled():
    assert "mountHeaderRepoLink(scope);" in JS, "never called from bootAll"
    # Material's own card stays hidden; ours takes its place.
    assert re.search(r"\.md-header__source\s*\{\s*display:\s*none", CSS)
    assert ".marimo-book-repo-link .marimo-book-button," in CSS or (
        ".marimo-book-repo-link .marimo-book-button {" in CSS
    )


def test_the_link_yields_to_a_github_launch_button():
    """Otherwise a notebook page shows two octocats in one header."""
    fn = JS.split("function mountHeaderRepoLink", 1)[1].split("\n  }", 1)[0]
    assert ".marimo-book-button-github" in fn


def test_the_link_is_removed_before_being_remounted():
    """Material instant-nav re-runs bootAll; without this it accumulates."""
    fn = JS.split("function mountHeaderRepoLink", 1)[1].split("\n  }", 1)[0]
    assert ".marimo-book-repo-link" in fn and "remove()" in fn
