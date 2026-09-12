"""Externalize and compress inline images at build time.

Every rendered image reaches the page as a ``data:`` URI: matplotlib output
via marimo's ``image/png`` MIME bundle, ``mo.image(path)`` (marimo embeds the
file bytes), nilearn's brainsprite mosaics, and — on WASM pages — the same
outputs a second time inside marimo's islands payload. Base64 costs 33 % on
top of the bytes, nothing is de-duplicated (a figure shown twice is embedded
twice), nothing is cached between pages, and a 20-inch figure rendered at
200 dpi is 4000 px wide on a 900 px column.

This transform:

1. decodes each inline image once per unique payload,
2. re-encodes raster images to WebP (lossy by default; alpha preserved),
   downscaling anything wider than ``Images.max_width`` — SVG and GIF pass
   through unchanged (vector / animation),
3. writes the result once to a content-addressed store
   (``assets/img/<sha256>.<ext>``) and points the page at it, with
   ``loading="lazy"``, ``decoding="async"`` and intrinsic ``width``/``height``
   on ``<img>`` tags so the browser can lay out before the bytes arrive.

Stores and staging mirror the anywidget buffer pipeline in
:mod:`.widget_state`: live renders park files in
``.marimo_book_cache/img/``, ``marimo-book render`` commits them under
``_rendered/img/``, and :func:`stage_referenced_images` copies whatever a
page references into ``docs/assets/img/`` at finalize time. Bodies keep the
site-root-relative form ``assets/img/…``; :func:`localize_asset_urls` turns it
into the right ``../`` chain for the page's depth when the page is written.
"""

from __future__ import annotations

import base64
import hashlib
import io
import os
import re
import shutil
from dataclasses import dataclass
from pathlib import Path

IMAGE_URL_PREFIX = "assets/img/"
_IMAGE_EXTS = ("webp", "png", "jpg", "gif", "svg")

_IMAGE_REF_RE = re.compile(
    re.escape(IMAGE_URL_PREFIX) + r"([0-9a-f]{64}\.(?:" + "|".join(_IMAGE_EXTS) + "))"
)
# A data URI anywhere in the page (attribute, escaped JSON, CSS url()).
_DATA_URI_RE = re.compile(r"data:image/(png|jpeg|jpg|gif|svg\+xml);base64,([A-Za-z0-9+/=]+)")
# An <img> tag whose src is a data URI; group 1 is everything before the
# URI, group 4 everything after it (attributes, self-close, >).
_IMG_TAG_RE = re.compile(
    r"(<img\b[^>]*?\bsrc=\")data:image/(png|jpeg|jpg|gif|svg\+xml);base64,([A-Za-z0-9+/=]+)(\"[^>]*>)",
    re.IGNORECASE,
)
# Only prefix references that are not already relative (``../assets``) or
# absolute (``/assets``).
_LOCALIZE_RE = re.compile(r"(?<![/.])" + re.escape(IMAGE_URL_PREFIX))

_FENCE_RE = re.compile(r"(```[\s\S]*?```)")

_MIME_EXT = {"png": "png", "jpeg": "jpg", "jpg": "jpg", "gif": "gif", "svg+xml": "svg"}


@dataclass(frozen=True)
class ImageOptions:
    """Build-time image policy (``book.yml`` → ``images:``)."""

    enabled: bool = True
    format: str = "webp"  # "webp" or "original" (externalize + de-duplicate only)
    quality: int = 85
    lossless: bool = False
    max_width: int = 1600
    # Payloads smaller than this stay inline: a request per icon-sized
    # image costs more than the bytes it saves.
    min_bytes: int = 4096

    @property
    def cache_key(self) -> str:
        return f"v1|{self.format}|{self.quality}|{int(self.lossless)}|{self.max_width}"


@dataclass(frozen=True)
class OptimizedImage:
    data: bytes
    ext: str
    width: int | None
    height: int | None


def optimize_image(data: bytes, mime: str, options: ImageOptions) -> OptimizedImage:
    """Re-encode one image per ``options``. Never raises: on any decode or
    encode failure the original bytes pass through with their own extension."""
    ext = _MIME_EXT.get(mime, "png")
    if ext in ("svg", "gif") or options.format == "original":
        return OptimizedImage(data, ext, None, None)
    try:
        from PIL import Image

        with Image.open(io.BytesIO(data)) as im:
            im.load()
            if getattr(im, "is_animated", False):
                return OptimizedImage(data, ext, im.width, im.height)
            width, height = im.size
            resized = False
            if options.max_width and width > options.max_width:
                new_h = max(1, round(height * options.max_width / width))
                im = im.resize((options.max_width, new_h), Image.LANCZOS)
                width, height = im.size
                resized = True
            has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
            im = im.convert("RGBA" if has_alpha else "RGB")
            # Photos and antialiased renders shrink most under lossy WebP;
            # flat line art (few colours) often shrinks more under lossless
            # and stays pixel-exact. Encode both unless lossless is forced
            # and keep the smaller.
            candidates: list[bytes] = []
            if not options.lossless:
                out = io.BytesIO()
                im.save(out, format="WEBP", quality=options.quality, method=6)
                candidates.append(out.getvalue())
            out = io.BytesIO()
            im.save(out, format="WEBP", lossless=True, method=6)
            candidates.append(out.getvalue())
            encoded = min(candidates, key=len)
            # Keep the original when re-encoding didn't help — unless we
            # downscaled, in which case the smaller pixel count is the point.
            if not resized and len(encoded) >= len(data):
                return OptimizedImage(data, ext, width, height)
            return OptimizedImage(encoded, "webp", width, height)
    except Exception:  # noqa: BLE001 — a bad image must not fail the build
        return OptimizedImage(data, ext, None, None)


class ImageStore:
    """Content-addressed image directory: ``<root>/<sha256>.<ext>``.

    The hash covers the *source* payload and the option set, so a page that
    embeds the same figure twice — or two pages that share a figure — write
    one file, and a policy change (quality, max_width) mints new names.
    """

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def name_for(self, payload: bytes, options: ImageOptions) -> str:
        return hashlib.sha256(options.cache_key.encode() + b"\0" + payload).hexdigest()

    def find(self, stem: str) -> str | None:
        """The stored file name for a source hash, if any extension exists."""
        for ext in _IMAGE_EXTS:
            if (self.root / f"{stem}.{ext}").is_file():
                return f"{stem}.{ext}"
        return None

    def put(self, stem: str, image: OptimizedImage) -> str:
        name = f"{stem}.{image.ext}"
        path = self.root / name
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_bytes(image.data)
            os.replace(tmp, path)
        return name

    def path(self, name: str) -> Path:
        return self.root / name

    def has(self, name: str) -> bool:
        return self.path(name).is_file()

    def copy_from(self, name: str, source: ImageStore) -> bool:
        if self.has(name):
            return True
        if not source.has(name):
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.path(name), self.path(name))
        return True

    def prune(self, keep: set[str]) -> None:
        if not self.root.exists():
            return
        try:
            for f in self.root.iterdir():
                if f.is_file() and f.name not in keep and f.suffix.lstrip(".") in _IMAGE_EXTS:
                    f.unlink(missing_ok=True)
        except OSError:
            pass


def _stored_image(path: Path) -> OptimizedImage | None:
    """Dimensions of an already-stored raster, so cache hits still emit
    intrinsic width/height on the tag."""
    if path.suffix not in (".webp", ".png", ".jpg"):
        return None
    try:
        from PIL import Image

        with Image.open(path) as im:
            return OptimizedImage(b"", path.suffix.lstrip("."), im.width, im.height)
    except Exception:  # noqa: BLE001
        return None


def image_rel_url(name: str) -> str:
    return f"{IMAGE_URL_PREFIX}{name}"


def externalize_images(html: str, store: ImageStore, options: ImageOptions) -> str:
    """Replace inline ``data:image/*`` URIs in ``html`` with store references.

    ``<img>`` tags get ``loading="lazy"``/``decoding="async"`` and intrinsic
    dimensions; bare URIs elsewhere (escaped JSON in precompute tables or
    marimo's islands payload, CSS) are swapped in place.
    """
    if not options.enabled or "data:image/" not in html:
        return html
    # Rendered bodies are Markdown: a data URI inside a ```fenced``` block is
    # the notebook's *source* on display, not an image — leave it verbatim.
    parts = _FENCE_RE.split(html)
    if len(parts) > 1:
        return "".join(
            part if part.startswith("```") else externalize_images(part, store, options)
            for part in parts
        )
    memo: dict[str, tuple[str, OptimizedImage | None]] = {}

    def resolve(mime: str, b64: str) -> tuple[str, OptimizedImage | None] | None:
        key = hashlib.sha1(b64.encode("ascii")).hexdigest()
        if key in memo:
            return memo[key]
        try:
            payload = base64.b64decode(b64, validate=False)
        except ValueError:
            memo[key] = ("", None)
            return None
        if len(payload) < options.min_bytes:
            memo[key] = ("", None)
            return None
        stem = store.name_for(payload, options)
        existing = store.find(stem)
        if existing is not None:
            memo[key] = (existing, _stored_image(store.path(existing)))
            return memo[key]
        image = optimize_image(payload, mime, options)
        name = store.put(stem, image)
        memo[key] = (name, image)
        return memo[key]

    def img_tag(m: re.Match) -> str:
        head, mime, b64, tail = m.group(1), m.group(2), m.group(3), m.group(4)
        res = resolve(mime, b64)
        if not res or not res[0]:
            return m.group(0)
        name, image = res
        extra = ""
        lowered = tail.lower()
        if "loading=" not in lowered:
            extra += ' loading="lazy"'
        if "decoding=" not in lowered:
            extra += ' decoding="async"'
        if image and image.width and "width=" not in lowered and "height=" not in lowered:
            extra += f' width="{image.width}" height="{image.height}"'
        # Insert the extra attributes right after the src attribute's closing quote.
        return f'{head}{image_rel_url(name)}"{extra}{tail[1:]}'

    html = _IMG_TAG_RE.sub(img_tag, html)

    def bare(m: re.Match) -> str:
        res = resolve(m.group(1), m.group(2))
        if not res or not res[0]:
            return m.group(0)
        return image_rel_url(res[0])

    return _DATA_URI_RE.sub(bare, html)


def referenced_image_names(body: str) -> set[str]:
    return set(_IMAGE_REF_RE.findall(body))


def stage_referenced_images(body: str, docs_dir: Path, sources: list[ImageStore]) -> list[str]:
    """Copy the images ``body`` references into ``docs/assets/img/``.

    Returns the names no source could supply.
    """
    names = referenced_image_names(body)
    if not names:
        return []
    dest = ImageStore(Path(docs_dir) / IMAGE_URL_PREFIX.rstrip("/"))
    missing: list[str] = []
    for name in sorted(names):
        if any(dest.copy_from(name, src) for src in sources):
            continue
        missing.append(name)
    return missing


def page_depth(rel_under_docs: Path) -> int:
    """How many ``../`` a page served at its mkdocs directory URL needs to
    reach the site root (``use_directory_urls`` is mkdocs' default)."""
    parts = Path(rel_under_docs).parts
    depth = len(parts)
    if parts and parts[-1] == "index.md":
        depth -= 1
    return depth


def localize_asset_urls(page: str, rel_under_docs: Path) -> str:
    """Rewrite site-root-relative ``assets/img/…`` references for the page's
    depth. Idempotent: already-relative or absolute references are skipped."""
    prefix = "../" * page_depth(rel_under_docs)
    if not prefix or IMAGE_URL_PREFIX not in page:
        return page
    return _LOCALIZE_RE.sub(prefix + IMAGE_URL_PREFIX, page)
