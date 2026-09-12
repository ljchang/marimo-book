"""Carry anywidget model state from the export kernel to the static page.

``marimo export ipynb --include-outputs`` renders each ``mo.ui.anywidget``
(and every anywidget marimo auto-wraps) as
``<marimo-anywidget data-model-id="…" data-js-url="…" data-initial-value='{"model_id": "…"}'>``.
The ES module travels with the element, but the widget's *state* — its
synced traits and any binary buffers (``traitlets.Bytes``) — lives only in
marimo's session view, which the ipynb exporter never writes out. On a
kernel-less page the shim therefore starts every widget from an empty model:
a scalar-only widget falls back to whatever defaults its JS hard-codes, and a
data-carrying widget (nltools' niivue viewer, a plotly ``FigureWidget``, …)
renders nothing at all.

This module closes that gap in three pieces:

1. **Recorder** — :mod:`marimo_book._export_runner` (the in-process
   execute-then-export script every ``export_notebook`` call runs) receives
   the finished ``session_view`` and, with ``--states``, dumps
   ``session_view.model_states`` — every model's traits, buffers, and
   ``_css`` — to a JSON sidecar next to the ipynb. Same process, same run,
   so the recorded ``model_id`` s are exactly the ones in the exported HTML.
   Serialization is best-effort: if marimo's internals move, the sidecar
   records the failure and the page degrades to today's behaviour.

2. **Buffer store** — a content-addressed directory of ``<sha256>.bin`` blobs.
   Buffers are written once per unique content (the same MNI background
   volume behind twenty viewers is one file) and referenced from the mount
   by a site-relative URL rather than inlined, so page HTML stays small and
   the browser fetches volumes lazily.

3. **Staging** — :func:`stage_referenced_buffers` copies the blobs a rendered
   body references into ``docs/assets/anywidget/`` at finalize time, from
   whichever store has them (the transient build cache for live renders, the
   committed ``_rendered/`` tree for ``mode: cached`` pages).

The runtime side lives in :file:`assets/marimo_book.js`: ``hydrateMount``
reads ``data-buffers``, fetches each blob, wraps it as a ``DataView`` at the
trait path anywidget's wire format names, and only then calls the widget's
``render``.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass, field
from pathlib import Path

# Where staged blobs land under ``docs/`` and how mounts reference them
# (site-root-relative; the shim resolves against the site root it derives
# from its own ``<script src>``).
BUFFER_URL_PREFIX = "assets/anywidget/"
BUFFER_SUFFIX = ".bin"

SIDECAR_VERSION = 1

_BUFFER_REF_RE = re.compile(
    re.escape(BUFFER_URL_PREFIX) + r"([0-9a-f]{64})" + re.escape(BUFFER_SUFFIX)
)


@dataclass
class WidgetModelState:
    """One anywidget model as recorded at export time."""

    state: dict = field(default_factory=dict)
    buffers: list[tuple[list, bytes]] = field(default_factory=list)
    css: str | None = None


@dataclass
class AnywidgetContext:
    """What the HTML rewriter needs to bake state into a mount.

    ``models`` is keyed by marimo's ``model_id`` (the mount's
    ``data-model-id``); ``store`` receives every buffer and hands back the
    content hash the mount references.
    """

    models: dict[str, WidgetModelState]
    store: BufferStore

    def get(self, model_id: str | None) -> WidgetModelState | None:
        if not model_id:
            return None
        return self.models.get(model_id)


def load_widget_states(sidecar: Path) -> dict[str, WidgetModelState]:
    """Parse the recorder's sidecar. Missing/corrupt → ``{}`` (degrade, never fail)."""
    sidecar = Path(sidecar)
    if not sidecar.exists():
        return {}
    try:
        data = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(data, dict) or data.get("version") != SIDECAR_VERSION:
        return {}
    out: dict[str, WidgetModelState] = {}
    for model_id, raw in (data.get("models") or {}).items():
        if not isinstance(raw, dict):
            continue
        buffers: list[tuple[list, bytes]] = []
        for b in raw.get("buffers") or []:
            try:
                buffers.append((list(b["path"]), base64.b64decode(b["b64"])))
            except (KeyError, TypeError, ValueError):
                continue
        state = raw.get("state")
        css = raw.get("css")
        out[str(model_id)] = WidgetModelState(
            state=state if isinstance(state, dict) else {},
            buffers=buffers,
            css=css if isinstance(css, str) and css else None,
        )
    return out


_GZIP_MAGIC = b"\x1f\x8b"


def normalize_gzip_mtime(blob: bytes) -> bytes:
    """Zero the MTIME field of a gzip member so identical payloads hash alike.

    ``gzip.compress()`` stamps the current time into bytes 4–8 of the header,
    so the same volume compressed on two exports yields different bytes and
    two blobs in the store (a precompute grid re-exports per slider value).
    The timestamp is metadata: zeroing it leaves a valid stream that inflates
    to the same payload. Non-gzip blobs pass through untouched.
    """
    if len(blob) >= 10 and blob[:2] == _GZIP_MAGIC and blob[4:8] != b"\x00\x00\x00\x00":
        return blob[:4] + b"\x00\x00\x00\x00" + blob[8:]
    return blob


class BufferStore:
    """Content-addressed blob directory: ``<root>/<sha256>.bin``."""

    def __init__(self, root: Path) -> None:
        self.root = Path(root)

    def put(self, blob: bytes) -> str:
        blob = normalize_gzip_mtime(blob)
        digest = hashlib.sha256(blob).hexdigest()
        path = self.path(digest)
        if not path.exists():
            self.root.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(".tmp")
            tmp.write_bytes(blob)
            os.replace(tmp, path)
        return digest

    def path(self, digest: str) -> Path:
        return self.root / f"{digest}{BUFFER_SUFFIX}"

    def has(self, digest: str) -> bool:
        return self.path(digest).is_file()

    def copy_from(self, digest: str, source: BufferStore) -> bool:
        """Import one blob from another store. ``False`` when the source lacks it."""
        if self.has(digest):
            return True
        if not source.has(digest):
            return False
        self.root.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source.path(digest), self.path(digest))
        return True

    def prune(self, keep: set[str]) -> None:
        """Delete every blob whose hash is not in ``keep`` (best effort)."""
        if not self.root.exists():
            return
        try:
            for f in self.root.glob(f"*{BUFFER_SUFFIX}"):
                if f.stem not in keep:
                    f.unlink(missing_ok=True)
        except OSError:
            pass


def buffer_rel_url(digest: str) -> str:
    return f"{BUFFER_URL_PREFIX}{digest}{BUFFER_SUFFIX}"


def referenced_buffer_hashes(body: str) -> set[str]:
    """Every buffer a rendered body's mounts reference, by content hash."""
    return set(_BUFFER_REF_RE.findall(body))


def stage_referenced_buffers(body: str, docs_dir: Path, sources: list[BufferStore]) -> list[str]:
    """Copy the blobs ``body`` references into ``docs_dir/assets/anywidget/``.

    Tries ``sources`` in order. Returns the hashes no source could supply —
    the caller decides whether that is a warning or a build error.
    """
    hashes = referenced_buffer_hashes(body)
    if not hashes:
        return []
    dest = BufferStore(Path(docs_dir) / BUFFER_URL_PREFIX.rstrip("/"))
    missing: list[str] = []
    for digest in sorted(hashes):
        if any(dest.copy_from(digest, src) for src in sources):
            continue
        missing.append(digest)
    return missing
