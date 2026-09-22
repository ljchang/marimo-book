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
    assert ".marimo-book-anywidget[data-mb-hydrated]" in _function("holdBakedFrames")


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
