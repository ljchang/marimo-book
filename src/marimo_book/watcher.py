"""Watchdog-driven rebuild loop for ``marimo-book serve``.

Watches the source tree (``content/`` plus ``book.yml``) and re-runs the
preprocessor whenever a tracked file changes. Mkdocs's own livereload
picks up the resulting ``_site_src/docs/`` updates and refreshes the
browser.

Kept deliberately simple for v0.1:

- **Full rebuild on every change.** Per-file incremental staging is a
  later optimization; full rebuild keeps the ``_site_src/`` tree in a
  consistent state.
- **Debounced.** Editors emit multiple filesystem events per save
  (temp file + rename + mtime bump); a small coalescing window
  prevents a storm of builds.
- **Reloads book.yml on each build**, so edits to TOC / theme / widget
  defaults apply without restarting the serve process.
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Callable

import yaml
from pydantic import ValidationError
from watchdog.events import FileSystemEvent, FileSystemEventHandler
from watchdog.observers import Observer

from .config import Book, load_book
from .preprocessor import BuildReport, Preprocessor

# File extensions that, when changed under ``content/``, trigger a rebuild.
# Anything else (notebook execution caches, .nii.gz spills) is ignored so the
# notebook's own side-effects don't bounce the build.
_TRACKED_SUFFIXES = {".md", ".py", ".yml", ".yaml", ".bib"}

# Directory names that never warrant a rebuild — marimo's session cache,
# Python bytecode, editor swap dirs.
_IGNORED_DIR_NAMES = {"__marimo__", "__pycache__", ".ipynb_checkpoints"}


class RebuildHandler(FileSystemEventHandler):
    """Coalesces filesystem events into a single rebuild call."""

    def __init__(
        self,
        *,
        book_file: Path,
        book_dir: Path,
        site_src: Path,
        debounce_seconds: float = 0.4,
        on_report: Callable[[BuildReport], None] | None = None,
    ) -> None:
        self.book_file = Path(book_file).resolve()
        self.book_dir = Path(book_dir).resolve()
        self.site_src = Path(site_src).resolve()
        self.debounce = debounce_seconds
        self.on_report = on_report

        self._lock = threading.Lock()
        self._pending = False
        self._last_event_time = 0.0
        self._timer: threading.Timer | None = None

    # --- watchdog entry points ------------------------------------------------

    def on_modified(self, event: FileSystemEvent) -> None:
        self._maybe_schedule(event)

    def on_created(self, event: FileSystemEvent) -> None:
        self._maybe_schedule(event)

    def on_deleted(self, event: FileSystemEvent) -> None:
        self._maybe_schedule(event)

    def on_moved(self, event: FileSystemEvent) -> None:
        self._maybe_schedule(event)

    # --- internals ------------------------------------------------------------

    def _maybe_schedule(self, event: FileSystemEvent) -> None:
        if event.is_directory:
            return
        path = Path(getattr(event, "dest_path", None) or event.src_path)
        if not self._is_tracked(path):
            return
        with self._lock:
            self._last_event_time = time.time()
            if self._timer is None:
                self._timer = threading.Timer(self.debounce, self._rebuild)
                self._timer.daemon = True
                self._timer.start()

    def _is_tracked(self, path: Path) -> bool:
        if path.suffix.lower() not in _TRACKED_SUFFIXES:
            return False
        # Skip events inside ignored directories at any depth.
        if any(part in _IGNORED_DIR_NAMES for part in path.parts):
            return False
        # Book.yml at the root, anything under book_dir/content, or any
        # *.bib file anywhere in the tree.
        try:
            rel = path.resolve().relative_to(self.book_dir)
        except ValueError:
            return False
        first = rel.parts[0] if rel.parts else ""
        if path.resolve() == self.book_file:
            return True
        if first == "content":
            return True
        if path.suffix.lower() == ".bib":
            return True
        return False

    def _rebuild(self) -> None:
        with self._lock:
            self._timer = None
        try:
            book = load_book(self.book_file)
        except (ValidationError, FileNotFoundError, yaml.YAMLError, ValueError) as exc:
            self._emit_error(f"book.yml: {exc.__class__.__name__}: {exc}")
            return

        try:
            report = Preprocessor(book, book_dir=self.book_dir).build(
                out_dir=self.site_src
            )
        except Exception as exc:  # noqa: BLE001 — keep the watcher alive
            self._emit_error(f"preprocessor crashed: {exc.__class__.__name__}: {exc}")
            return

        if self.on_report is not None:
            self.on_report(report)


    def _emit_error(self, message: str) -> None:
        if self.on_report is None:
            return
        report = BuildReport()
        report.errors.append(message)
        self.on_report(report)


# --- convenience wrapper ----------------------------------------------------


def start_watcher(
    *,
    book_file: Path,
    book_dir: Path,
    site_src: Path,
    on_report: Callable[[BuildReport], None] | None = None,
) -> tuple[Observer, RebuildHandler]:
    """Install the rebuild handler on a watchdog Observer and start it.

    Returns the observer and handler so the caller can ``observer.stop()``
    on shutdown.
    """
    handler = RebuildHandler(
        book_file=book_file,
        book_dir=book_dir,
        site_src=site_src,
        on_report=on_report,
    )
    observer = Observer()
    # Watch content/ recursively for .md / .py changes.
    content_dir = book_dir / "content"
    if content_dir.exists():
        observer.schedule(handler, str(content_dir), recursive=True)
    # Watch the book_dir non-recursively so we catch book.yml + top-level .bib.
    observer.schedule(handler, str(book_dir), recursive=False)
    observer.start()
    return observer, handler
