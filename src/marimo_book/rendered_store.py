"""Committed, version-controllable cache of rendered notebook bodies.

``mode: cached`` notebooks don't execute at build time. Instead their
rendered body (the expensive ``marimo export`` output, with cell outputs
embedded as HTML/base64) is regenerated once by the author via
``marimo-book render`` and committed under ``_rendered/``. A plain CI
runner then reuses it — no Python deps, no GPU, no execution — which is
the marimo-book analogue of jupyter-book's ``execute: off``.

What is stored is the *body only* (pre-button, pre-link-rewrite), so that
changing ``launch_buttons``, the repo URL, or the TOC does not invalidate
the artifact — only a change to the notebook source does. Freshness is a
single check: ``sha256(source) == manifest[src].src_hash``.

Layout under the book directory::

    _rendered/
      manifest.json                 # src_rel -> {src_hash, body_path, ...}
      content/01_basics.md          # rendered body, mirrors source path
      anywidget/<sha256>.bin        # widget buffers the bodies reference
      img/<sha256>.<ext>            # externalized images the bodies reference

Unlike ``.marimo_book_cache/`` (transient, gitignored), ``_rendered/`` is
meant to be committed.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as _pkg_version
from pathlib import Path

from .transforms.images import ImageStore, referenced_image_names
from .transforms.widget_state import BufferStore, referenced_buffer_hashes

_DIR_NAME = "_rendered"
_MANIFEST_NAME = "manifest.json"
# v2 adds ``body_sig`` to each entry (render-affecting config + tool version).
# Bumping the schema invalidates any v1 manifest wholesale, forcing a re-render.
_SCHEMA_VERSION = 2


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _tool_version() -> str:
    try:
        return _pkg_version("marimo-book")
    except PackageNotFoundError:
        return "0+unknown"


class RenderedStore:
    """Read/write the committed ``_rendered/`` artifact for cached pages."""

    def __init__(self, book_dir: Path, *, dir_name: str = _DIR_NAME) -> None:
        self.root = Path(book_dir).resolve() / dir_name
        self.manifest_path = self.root / _MANIFEST_NAME
        self.entries: dict[str, dict] = {}
        self.dirty = False
        self._load()

    @property
    def buffer_store(self) -> BufferStore:
        """Committed anywidget buffers (``_rendered/anywidget/``)."""
        return BufferStore(self.root / "anywidget")

    @property
    def image_store(self) -> ImageStore:
        """Committed externalized images (``_rendered/img/``)."""
        return ImageStore(self.root / "img")

    # --- read side (build) ---------------------------------------------------

    def is_fresh(self, src_rel: str, src_abs: Path, *, body_sig: str | None = None) -> bool:
        """True when a committed body exists and matches the current source.

        When ``body_sig`` is given it must also equal the signature stored at
        render time — a hash of the render-affecting config (``defaults``,
        ``dependencies``, ``widget_defaults``) plus the marimo-book version. A
        change there means the committed body would render differently now, so
        the artifact is stale even though the source bytes are unchanged.
        ``body_sig=None`` skips that check (source-hash only).
        """
        entry = self.entries.get(src_rel)
        if entry is None:
            return False
        body_abs = self.root / entry["body_path"]
        if not body_abs.exists():
            return False
        if body_sig is not None and entry.get("body_sig") != body_sig:
            return False
        if self._missing_buffers(entry) or self._missing_images(entry):
            return False
        try:
            return _sha256(src_abs) == entry["src_hash"]
        except OSError:
            return False

    def reason_stale(self, src_rel: str, src_abs: Path, *, body_sig: str | None = None) -> str:
        """Human-readable explanation for a non-fresh entry (for warnings)."""
        entry = self.entries.get(src_rel)
        if entry is None:
            return "no committed output"
        if not (self.root / entry["body_path"]).exists():
            return "committed body file is missing"
        if body_sig is not None and entry.get("body_sig") != body_sig:
            return "render configuration or marimo-book version changed since it was last rendered"
        if self._missing_buffers(entry):
            return "committed anywidget buffer file is missing"
        if self._missing_images(entry):
            return "committed image file is missing"
        return "source has changed since it was last rendered"

    def read_body(self, src_rel: str) -> str:
        """Return the committed rendered body for ``src_rel``."""
        entry = self.entries[src_rel]
        return (self.root / entry["body_path"]).read_text(encoding="utf-8")

    # --- write side (`marimo-book render`) -----------------------------------

    def write(
        self,
        src_rel: str,
        src_abs: Path,
        body: str,
        *,
        body_sig: str | None = None,
        cell_errors: list[dict] | None = None,
        buffer_source: BufferStore | None = None,
        image_source: ImageStore | None = None,
    ) -> None:
        """Persist a freshly rendered ``body`` and record its source hash.

        The body file mirrors the source path with a ``.md`` suffix so the
        committed tree is human-recognizable and collision-free even when the
        page maps to ``index.md`` in the built site. ``body_sig`` records the
        render-affecting config + tool version so a later build can detect a
        stale artifact even when the source bytes are unchanged.
        ``cell_errors`` records any raising cells so a later ``build --strict``
        can fail on a committed traceback without executing anything.
        ``buffer_source`` is the transient store the render wrote anywidget
        buffers into; every blob the body references is copied under
        ``_rendered/anywidget/`` so the committed artifact is self-contained.
        """
        body_rel = Path(src_rel).with_suffix(".md").as_posix()
        body_abs = self.root / body_rel
        body_abs.parent.mkdir(parents=True, exist_ok=True)
        body_abs.write_text(body, encoding="utf-8")
        buffers = sorted(referenced_buffer_hashes(body))
        if buffers and buffer_source is not None:
            own = self.buffer_store
            for digest in buffers:
                own.copy_from(digest, buffer_source)
        images = sorted(referenced_image_names(body))
        if images and image_source is not None:
            own_images = self.image_store
            for name in images:
                own_images.copy_from(name, image_source)
        self.entries[src_rel] = {
            "src_hash": _sha256(src_abs),
            "body_path": body_rel,
            "body_sig": body_sig,
            "rendered_at": datetime.now(UTC).isoformat(timespec="seconds"),
            "marimo_book_version": _tool_version(),
            "cell_errors": cell_errors or [],
            "buffers": buffers,
            "images": images,
        }
        self.dirty = True

    def recorded_cell_errors(self, src_rel: str) -> list[dict]:
        """Raising cells captured at render time.

        Entries committed before this key existed return ``[]`` — they are
        grandfathered rather than schema-bumped, because a bump would mark
        every committed body stale and force re-executing heavy notebooks.
        """
        entry = self.entries.get(src_rel) or {}
        raw = entry.get("cell_errors")
        return raw if isinstance(raw, list) else []

    def save(self) -> None:
        if not self.dirty and self.manifest_path.exists():
            return
        self.root.mkdir(parents=True, exist_ok=True)
        payload = {
            "schema_version": _SCHEMA_VERSION,
            "entries": self.entries,
        }
        self.manifest_path.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        keep = {d for e in self.entries.values() for d in (e.get("buffers") or [])}
        self.buffer_store.prune(keep)
        keep_images = {n for e in self.entries.values() for n in (e.get("images") or [])}
        self.image_store.prune(keep_images)
        self.dirty = False

    def _missing_buffers(self, entry: dict) -> list[str]:
        store = self.buffer_store
        return [d for d in (entry.get("buffers") or []) if not store.has(d)]

    def _missing_images(self, entry: dict) -> list[str]:
        store = self.image_store
        return [n for n in (entry.get("images") or []) if not store.has(n)]

    # --- internals -----------------------------------------------------------

    def _load(self) -> None:
        if not self.manifest_path.exists():
            return
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return  # corrupt/absent manifest → treat everything as stale
        if data.get("schema_version") != _SCHEMA_VERSION:
            return
        loaded = data.get("entries", {})
        if isinstance(loaded, dict):
            self.entries = loaded
