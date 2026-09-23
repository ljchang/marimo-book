"""The baked widget is held over a WASM island while the live one mounts.

On a WASM page the shim paints every anywidget from its baked state at load.
When Pyodide is up, marimo's islands runtime repaints each island and the
baked mount is replaced by a live ``<marimo-anywidget>`` that is empty until
its module arrives from the kernel -- 250-900 ms per widget on DartBrains'
MR_Physics -- so readers saw widgets load, vanish, and come back.
``holdBakedFrames`` puts the replaced mount back as an inert overlay and keeps
the island's height until the live widget has drawn. There is no JS test
runner here; these pin the parts the behaviour depends on. It was checked
against the live runtime in a browser (9 overlays up and down, none left).
"""

from __future__ import annotations

import re
from pathlib import Path

ASSETS = Path(__file__).resolve().parents[1] / "src" / "marimo_book" / "assets"
JS = (ASSETS / "marimo_book.js").read_text()
CSS = (ASSETS / "extra.css").read_text()


def _function(name: str) -> str:
    start = JS.index(f"function {name}(")
    return JS[start : JS.index("\n  }\n", start)]


def test_boot_holds_frames_after_hydrating():
    boot = _function("bootAll")
    assert boot.index("hydrateAll(scope)") < boot.index("holdBakedFrames(scope)")


def test_it_holds_the_latest_hydrated_mount_not_the_first():
    # Payload materialization swaps in fresh build-time markup that is
    # hydrated again; holding the first mount would put back a stale node.
    assert "hydratedMounts.has(el)" in _function("holdBakedFrames")


def test_serialized_copies_of_hydrated_mounts_are_rendered_again():
    # At kernel start marimo re-inserts a serialized copy of each hydrated
    # island. The copy keeps data-mb-hydrated but has blank canvases and no
    # render loop, so the attribute can't gate hydration: every MR_Physics
    # widget sat empty from ~7 s until the live widget drew.
    hydrate = _function("hydrateAll")
    assert "hydratedMounts.has(el)" in hydrate
    assert ":not([data-mb-hydrated])" not in hydrate
    watch = _function("watchMountCopies")
    assert "new MutationObserver" in watch and "hydrateAll(" in watch
    assert "watchMountCopies();" in JS


def test_removed_widgets_are_cleaned_up():
    # Otherwise each replaced mount's render loop keeps drawing into a
    # detached canvas for the life of the page.
    assert "__marimoBookCleanup" in _function("watchMountCopies")
    # A mount replaced before render() resolved is cleaned up right away.
    assert "else cleanup();" in _function("hydrateMount")


def test_the_live_widget_is_never_touched():
    # Rewrapping marimo's runtime element is what broke widgets on 0.24; the
    # hold only reads it and adds a sibling overlay.
    hold = _function("holdBakedFrames")
    assert not re.search(r"\blive\.(append|replace|remove|setAttribute|innerHTML)", hold)
    assert "island.appendChild(overlay)" in hold


def test_the_overlay_always_lifts():
    hold = _function("holdBakedFrames")
    assert "HOLD_TIMEOUT_MS" in hold and "!live.isConnected" in hold
    assert "setTimeout(go" in _function("afterPaint")  # background tabs pause frames


def test_the_overlay_is_inert():
    rule = CSS.split(".marimo-book-held-frame", 1)[1].split("}", 1)[0]
    assert "pointer-events: none" in rule and "position: absolute" in rule
