"""Build-time image externalization + compression (transforms/images.py)."""

from __future__ import annotations

import base64
import io
import json
import re
import shutil
from pathlib import Path

from PIL import Image, ImageDraw

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor, _transient_image_store
from marimo_book.rendered_store import RenderedStore
from marimo_book.transforms.images import (
    IMAGE_URL_PREFIX,
    ImageOptions,
    ImageStore,
    externalize_images,
    image_rel_url,
    localize_asset_urls,
    optimize_image,
    page_depth,
    referenced_image_names,
    stage_referenced_images,
)


def _png(width: int = 400, height: int = 200, alpha: bool = False) -> bytes:
    """A render-like PNG: smooth gradient background (antialiased-figure
    territory, where lossy WebP wins) plus lines and text."""
    im = Image.new("RGBA" if alpha else "RGB", (width, height))
    px = im.load()
    for y in range(height):
        for x in range(width):
            v = (x * 255 // max(1, width - 1), y * 255 // max(1, height - 1), 200)
            if alpha:
                transparent = x == width - 1 and y == height - 1
                px[x, y] = (*v, 0 if transparent else 255)
            else:
                px[x, y] = v
    d = ImageDraw.Draw(im)
    for i in range(0, width, 7):
        d.line([(i, 0), (width - i, height)], fill=(30, 90, 200), width=2)
    if width >= 40 and height >= 40:
        d.rectangle([10, 10, width // 3, height // 3], outline="black", width=3)
        d.text((20, 20), "figure", fill="black")
    out = io.BytesIO()
    im.save(out, format="PNG")
    return out.getvalue()


def _uri(data: bytes, mime: str = "image/png") -> str:
    return f"data:{mime};base64,{base64.b64encode(data).decode()}"


OPTS = ImageOptions()


# --- optimize -----------------------------------------------------------------


def test_optimize_reencodes_png_to_smaller_webp() -> None:
    png = _png(800, 400)
    out = optimize_image(png, "png", OPTS)
    assert out.ext == "webp"
    assert len(out.data) < len(png)  # synthetic art; real figures shrink far more
    assert (out.width, out.height) == (800, 400)
    with Image.open(io.BytesIO(out.data)) as im:
        assert im.format == "WEBP"


def test_optimize_downscales_wide_images_keeping_aspect() -> None:
    out = optimize_image(_png(4000, 1000), "png", ImageOptions(max_width=1600))
    assert (out.width, out.height) == (1600, 400)
    with Image.open(io.BytesIO(out.data)) as im:
        assert im.size == (1600, 400)


def test_optimize_preserves_alpha() -> None:
    out = optimize_image(_png(300, 150, alpha=True), "png", OPTS)
    with Image.open(io.BytesIO(out.data)) as im:
        assert im.mode == "RGBA"
        assert im.getpixel((299, 149))[3] == 0  # still transparent


def test_optimize_passes_svg_gif_and_original_mode_through() -> None:
    svg = b"<svg xmlns='http://www.w3.org/2000/svg'></svg>"
    assert optimize_image(svg, "svg+xml", OPTS) == optimize_image(svg, "svg+xml", OPTS)
    assert optimize_image(svg, "svg+xml", OPTS).ext == "svg"
    assert optimize_image(svg, "svg+xml", OPTS).data == svg
    gif = b"GIF89a\x01\x00\x01\x00\x00\x00\x00;"
    assert optimize_image(gif, "gif", OPTS).ext == "gif"
    png = _png()
    orig = optimize_image(png, "png", ImageOptions(format="original"))
    assert orig.ext == "png" and orig.data == png


def test_optimize_keeps_original_when_webp_is_not_smaller_and_never_raises() -> None:
    tiny = _png(8, 8)
    out = optimize_image(tiny, "png", ImageOptions(min_bytes=0))
    assert out.data in (tiny,) or out.ext == "webp"
    garbage = optimize_image(b"not an image", "png", OPTS)
    assert garbage.data == b"not an image" and garbage.ext == "png"


# --- externalize --------------------------------------------------------------


def test_externalize_rewrites_img_tags_deduplicates_and_handles_escaped_json(
    tmp_path: Path,
) -> None:
    store = ImageStore(tmp_path / "img")
    png = _png(2000, 500)
    uri = _uri(png)
    table = json.dumps({"1": '<img src="' + uri + '">'})
    html = (
        f'<div><img src="{uri}" /></div>\n'
        f'<p><img alt="x" src="{uri}" width="10" height="5"></p>\n'
        f'<script type="application/json">{table}</script>'
    )
    out = externalize_images(html, store, OPTS)
    assert "data:image" not in out
    names = referenced_image_names(out)
    assert len(names) == 1  # same payload three times → one file
    (name,) = names
    assert name.endswith(".webp")
    assert store.has(name)
    tags = re.findall(r"<img[^>]*>", out)
    assert 'loading="lazy"' in tags[0] and 'decoding="async"' in tags[0]
    assert 'width="1600" height="400"' in tags[0]  # intrinsic size after downscale
    assert 'width="10" height="5"' in tags[1] and 'width="1600"' not in tags[1]  # author's wins
    # Escaped-JSON occurrence swapped in place (the tag regex can't see it).
    assert 'src=\\"' + image_rel_url(name) + '\\"' in out
    # A second pass (e.g. a re-export hitting the same store) reuses the file
    # and still knows the dimensions.
    again = externalize_images(html, store, OPTS)
    assert again == out


def test_externalize_leaves_tiny_images_inline_and_svg_as_files(tmp_path: Path) -> None:
    store = ImageStore(tmp_path / "img")
    tiny = _uri(_png(4, 4))
    svg = (
        b"<svg xmlns='http://www.w3.org/2000/svg' width='10' height='10'>"
        + b"<rect/>" * 800
        + b"</svg>"
    )
    html = f'<img src="{tiny}"><img src="{_uri(svg, "image/svg+xml")}">'
    out = externalize_images(html, store, OPTS)
    assert tiny in out  # below min_bytes → untouched
    (name,) = referenced_image_names(out)
    assert name.endswith(".svg") and store.path(name).read_bytes() == svg


def test_externalize_disabled_is_a_no_op(tmp_path: Path) -> None:
    html = f'<img src="{_uri(_png())}">'
    assert externalize_images(html, ImageStore(tmp_path), ImageOptions(enabled=False)) == html


# --- staging / localizing -----------------------------------------------------


def test_page_depth_and_localize() -> None:
    assert page_depth(Path("index.md")) == 0
    assert page_depth(Path("Chapter.md")) == 1
    assert page_depth(Path("part/Chapter.md")) == 2
    assert page_depth(Path("part/index.md")) == 1
    name = "a" * 64 + ".webp"
    body = f'<img src="{IMAGE_URL_PREFIX}{name}"> ../{IMAGE_URL_PREFIX}{name} /{IMAGE_URL_PREFIX}{name}'
    out = localize_asset_urls(body, Path("part/Chapter.md"))
    assert f'src="../../{IMAGE_URL_PREFIX}{name}"' in out
    assert (
        f" ../{IMAGE_URL_PREFIX}{name}" in out and f" /{IMAGE_URL_PREFIX}{name}" in out
    )  # untouched
    assert localize_asset_urls(out, Path("part/Chapter.md")) == out  # idempotent
    assert localize_asset_urls(body, Path("index.md")) == body


def test_stage_referenced_images_copies_from_first_store_that_has_it(tmp_path: Path) -> None:
    transient = ImageStore(tmp_path / "t")
    committed = ImageStore(tmp_path / "c")
    a = transient.put("a" * 64, optimize_image(_png(), "png", OPTS))
    b = committed.put("b" * 64, optimize_image(_png(50, 50), "png", OPTS))
    ghost = "f" * 64 + ".webp"
    body = " ".join(image_rel_url(n) for n in (a, b, ghost))
    missing = stage_referenced_images(body, tmp_path / "docs", [transient, committed])
    assert missing == [ghost]
    assert (tmp_path / "docs" / IMAGE_URL_PREFIX / a).exists()
    assert (tmp_path / "docs" / IMAGE_URL_PREFIX / b).exists()


# --- end to end ---------------------------------------------------------------


def _book_with_image_notebook(book_dir: Path, png: bytes) -> Book:
    (book_dir / "content").mkdir()
    (book_dir / "content" / "intro.md").write_text("# Intro\n", encoding="utf-8")
    b64 = base64.b64encode(png).decode()
    (book_dir / "content" / "figs.py").write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.16'\n"
        "app = marimo.App()\n\n"
        "@app.cell\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        f"    mo.Html('<img src=\"data:image/png;base64,{b64}\">')\n"
        "    return\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        f"    mo.Html('<p>again</p><img src=\"data:image/png;base64,{b64}\">')\n"
        "    return\n",
        encoding="utf-8",
    )
    return Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": False},
            "toc": [{"file": "content/intro.md"}, {"file": "content/figs.py"}],
        }
    )


def test_build_externalizes_images_and_replays_on_cache_hit(tmp_path: Path) -> None:
    png = _png(2400, 600)
    book = _book_with_image_notebook(tmp_path, png)
    out_dir = tmp_path / "_site_src"
    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report.errors, report.errors

    page = (out_dir / "docs" / "figs.md").read_text(encoding="utf-8")
    tags = re.findall(r"<img[^>]*>", page)
    rendered = [t for t in tags if "data:image" not in t]
    # Two rendered outputs; the two ```python fences still show the source
    # data URIs verbatim (they are code on display, not images).
    assert len(rendered) == 2 and page.count("data:image") == 2
    names = referenced_image_names(page)
    assert len(names) == 1  # figure shown twice → one file
    (name,) = names
    assert f'src="../{IMAGE_URL_PREFIX}{name}"' in page  # figs.md → /figs/ → one level up
    assert 'loading="lazy"' in rendered[0] and 'width="1600" height="400"' in rendered[0]
    staged = out_dir / "docs" / IMAGE_URL_PREFIX / name
    assert staged.exists() and staged.stat().st_size < len(png) // 2  # 2400 → 1600 px
    assert _transient_image_store(tmp_path).has(name)

    # Cache hit must re-stage the file into a wiped docs tree.
    shutil.rmtree(out_dir)
    report2 = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report2.errors and report2.pages_cached == 1
    assert staged.exists()

    # A missing store file invalidates the hit instead of shipping a 404.
    _transient_image_store(tmp_path).path(name).unlink()
    shutil.rmtree(out_dir)
    report3 = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report3.errors and report3.pages_cached == 0
    assert staged.exists()


def test_rendered_store_commits_images_and_tracks_them(tmp_path: Path) -> None:
    transient = ImageStore(tmp_path / "transient")
    name = transient.put("c" * 64, optimize_image(_png(), "png", OPTS))
    body = f'<img src="{image_rel_url(name)}">'
    src = tmp_path / "nb.py"
    src.write_text("x = 1\n", encoding="utf-8")
    store = RenderedStore(tmp_path)
    store.write("nb.py", src, body, body_sig="sig", image_source=transient)
    store.save()
    assert store.image_store.has(name)
    assert store.entries["nb.py"]["images"] == [name]
    assert store.is_fresh("nb.py", src, body_sig="sig")
    store.image_store.path(name).unlink()
    assert not store.is_fresh("nb.py", src, body_sig="sig")
    assert "image" in store.reason_stale("nb.py", src, body_sig="sig")


def test_blog_notebook_post_stages_and_localizes_images(tmp_path: Path) -> None:
    """Blog posts are written by _stage_blog, not _finalize_page — they need
    the same asset staging, and URLs relative to blog/posts/<stem>/."""
    png = _png(600, 300)
    book = _book_with_image_notebook(tmp_path, png)
    payload = book.model_dump(mode="json")
    payload["blog"] = {"enabled": True}
    book = Book.model_validate(payload)
    posts = tmp_path / "blog" / "posts"
    posts.mkdir(parents=True)
    src = tmp_path / "content" / "figs.py"
    post = posts / "2026-09-12-figs.py"
    post.write_text(
        '# /// blog\n# title = "Figures"\n# date = "2026-09-12"\n# ///\n'
        + src.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    out_dir = tmp_path / "_site_src"
    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report.errors, report.errors
    staged_post = out_dir / "docs" / "blog" / "posts" / "2026-09-12-figs.md"
    page = staged_post.read_text(encoding="utf-8")
    names = referenced_image_names(page)
    assert len(names) == 1
    (name,) = names
    assert f'src="../../../{IMAGE_URL_PREFIX}{name}"' in page  # /blog/posts/<stem>/ → three up
    assert (out_dir / "docs" / IMAGE_URL_PREFIX / name).exists()
