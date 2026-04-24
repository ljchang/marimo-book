"""Tests for the link_rewrites transform."""

from __future__ import annotations

from marimo_book.transforms.link_rewrites import (
    apply_link_rewrites,
    rewrite_ipynb_links,
    rewrite_parent_image_paths,
)


# --- rewrite_ipynb_links -----------------------------------------------------


def test_ipynb_link_rewritten_when_target_exists() -> None:
    md = "See [connectivity](Connectivity.ipynb) for details."
    out = rewrite_ipynb_links(md, {"Connectivity"})
    assert out == "See [connectivity](Connectivity.md) for details."


def test_ipynb_link_preserved_when_target_unknown() -> None:
    md = "See [example](ExternalExample.ipynb)."
    out = rewrite_ipynb_links(md, {"Connectivity"})
    assert out == md  # unchanged


def test_ipynb_link_with_fragment_rewritten() -> None:
    md = "See [this](GLM.ipynb#hrf) section."
    out = rewrite_ipynb_links(md, {"GLM"})
    assert out == "See [this](GLM.md#hrf) section."


def test_ipynb_link_with_directory_component_rewritten() -> None:
    md = "See [chapter](../other/Deep.ipynb)."
    out = rewrite_ipynb_links(md, {"Deep"})
    assert out == "See [chapter](../other/Deep.md)."


def test_absolute_url_ipynb_left_alone() -> None:
    md = "See [original](https://colab.google/Foo.ipynb)."
    out = rewrite_ipynb_links(md, {"Foo"})
    assert out == md  # absolute URL skipped


# --- rewrite_parent_image_paths ----------------------------------------------


def test_parent_image_in_markdown_link_rewritten() -> None:
    md = "![alt](../images/foo.png)"
    out = rewrite_parent_image_paths(md)
    assert out == "![alt](images/foo.png)"


def test_parent_image_in_html_src_rewritten() -> None:
    md = '<img src="../images/foo.png" />'
    out = rewrite_parent_image_paths(md)
    assert out == '<img src="images/foo.png" />'


def test_parent_image_in_html_href_rewritten() -> None:
    md = '<a href="../images/lectures/slides.pdf">slides</a>'
    out = rewrite_parent_image_paths(md)
    assert out == '<a href="images/lectures/slides.pdf">slides</a>'


def test_non_parent_images_left_alone() -> None:
    md = "![ok](images/foo.png) [also ok](/images/foo.png)"
    out = rewrite_parent_image_paths(md)
    assert out == md  # no ../ to rewrite


# --- apply_link_rewrites (integration) --------------------------------------


def test_apply_link_rewrites_runs_both() -> None:
    md = "[next](GLM.ipynb) and ![fig](../images/bar.png)"
    out = apply_link_rewrites(md, md_basenames={"GLM"})
    assert "[next](GLM.md)" in out
    assert "![fig](images/bar.png)" in out


def test_apply_link_rewrites_without_basenames_skips_ipynb() -> None:
    md = "[x](GLM.ipynb) and ![f](../images/bar.png)"
    out = apply_link_rewrites(md, md_basenames=None)
    assert "GLM.ipynb" in out  # ipynb untouched
    assert "images/bar.png" in out  # image path still rewritten
