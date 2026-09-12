"""Anywidget state baking: recorder, buffer store, mount rewrite, staging."""

from __future__ import annotations

import base64
import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from marimo_book.config import Book
from marimo_book.preprocessor import Preprocessor, _transient_buffer_store
from marimo_book.rendered_store import RenderedStore
from marimo_book.transforms.anywidgets import rewrite_anywidget_html
from marimo_book.transforms.marimo_export import cells_to_markdown, export_notebook
from marimo_book.transforms.widget_state import (
    BUFFER_URL_PREFIX,
    AnywidgetContext,
    BufferStore,
    WidgetModelState,
    buffer_rel_url,
    load_widget_states,
    referenced_buffer_hashes,
    stage_referenced_buffers,
)

FIXTURES = Path(__file__).parent / "fixtures"
ANYWIDGET_NOTEBOOK = FIXTURES / "anywidget_notebook.py"

_MOUNT = (
    '<marimo-anywidget data-initial-value=\'{"model_id":"m1"}\' '
    "data-js-url='\"data:text/javascript;base64,AAAA\"' data-js-hash='\"h1\"' "
    "data-model-id='\"m1\"' data-label='null'></marimo-anywidget>"
)


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


# --- buffer store -------------------------------------------------------------


def test_buffer_store_is_content_addressed_and_deduplicates(tmp_path: Path) -> None:
    store = BufferStore(tmp_path / "blobs")
    a = store.put(b"volume-a")
    again = store.put(b"volume-a")
    b = store.put(b"volume-b")
    assert a == again == _sha(b"volume-a")
    assert a != b
    assert store.has(a) and store.has(b)
    assert sorted(p.name for p in (tmp_path / "blobs").iterdir()) == sorted(
        [f"{a}.bin", f"{b}.bin"]
    )


def test_buffer_store_copy_from_and_prune(tmp_path: Path) -> None:
    src = BufferStore(tmp_path / "src")
    dst = BufferStore(tmp_path / "dst")
    a = src.put(b"aaa")
    assert dst.copy_from(a, src) is True
    assert dst.has(a)
    assert dst.copy_from("0" * 64, src) is False
    dst.prune(keep=set())
    assert not dst.has(a)


def test_referenced_buffer_hashes_and_url_round_trip() -> None:
    digest = _sha(b"x")
    body = (
        f'<div data-buffers=\'[{{"path": ["payload"], "url": "{buffer_rel_url(digest)}"}}]\'></div>'
    )
    assert referenced_buffer_hashes(body) == {digest}
    assert referenced_buffer_hashes("no mounts here") == set()


def test_stage_referenced_buffers_copies_from_first_store_that_has_it(tmp_path: Path) -> None:
    transient = BufferStore(tmp_path / "transient")
    committed = BufferStore(tmp_path / "committed")
    a = transient.put(b"aaa")
    b = committed.put(b"bbb")
    ghost = "f" * 64
    body = " ".join(buffer_rel_url(d) for d in (a, b, ghost))
    docs = tmp_path / "docs"
    missing = stage_referenced_buffers(body, docs, [transient, committed])
    assert missing == [ghost]
    staged = docs / BUFFER_URL_PREFIX
    assert (staged / f"{a}.bin").read_bytes() == b"aaa"
    assert (staged / f"{b}.bin").read_bytes() == b"bbb"


# --- sidecar ------------------------------------------------------------------


def test_load_widget_states_parses_sidecar_and_degrades(tmp_path: Path) -> None:
    sidecar = tmp_path / "widget_state.json"
    assert load_widget_states(sidecar) == {}
    sidecar.write_text("{not json", encoding="utf-8")
    assert load_widget_states(sidecar) == {}
    sidecar.write_text(json.dumps({"version": 99, "models": {}}), encoding="utf-8")
    assert load_widget_states(sidecar) == {}
    sidecar.write_text(
        json.dumps(
            {
                "version": 1,
                "models": {
                    "m1": {
                        "state": {"label": "x", "scale": 2.5},
                        "buffers": [
                            {"path": ["payload"], "b64": base64.b64encode(b"abc").decode()}
                        ],
                        "css": ".w{}",
                    },
                    "bad": "not-a-dict",
                },
            }
        ),
        encoding="utf-8",
    )
    states = load_widget_states(sidecar)
    assert set(states) == {"m1"}
    assert states["m1"].state == {"label": "x", "scale": 2.5}
    assert states["m1"].buffers == [(["payload"], b"abc")]
    assert states["m1"].css == ".w{}"


# --- mount rewrite ------------------------------------------------------------


def test_rewrite_bakes_recorded_state_buffers_and_css(tmp_path: Path) -> None:
    store = BufferStore(tmp_path / "blobs")
    ctx = AnywidgetContext(
        models={
            "m1": WidgetModelState(
                state={"label": "from-kernel", "scale": 2.5},
                buffers=[(["payload"], b"\x00\x01\x02"), (["empty"], b"")],
                css=".w { color: teal; }",
            )
        },
        store=store,
    )
    out = rewrite_anywidget_html(
        _mount_in_cell(),
        cell_source="w = BytesWidget(label='literal', scale=1.0, extra=7)",
        widget_defaults={"BytesWidget": {"scale": 0.5, "from_defaults": True}},
        anywidget_ctx=ctx,
    )
    div = _mount_div(out)
    initial = json.loads(_attr(div, "data-initial-value"))
    # Precedence: widget_defaults < literal kwargs < recorded kernel state.
    assert initial["label"] == "from-kernel"
    assert initial["scale"] == 2.5
    assert initial["extra"] == 7
    assert initial["from_defaults"] is True
    refs = json.loads(_attr(div, "data-buffers"))
    digest = _sha(b"\x00\x01\x02")
    assert refs == [
        {"path": ["payload"], "url": buffer_rel_url(digest), "size": 3},
        {"path": ["empty"], "empty": True},
    ]
    assert store.path(digest).read_bytes() == b"\x00\x01\x02"
    assert _attr(div, "data-css") == ".w { color: teal; }"
    assert referenced_buffer_hashes(out) == {digest}


def test_rewrite_without_recorded_model_is_unchanged(tmp_path: Path) -> None:
    ctx = AnywidgetContext(models={"other": WidgetModelState()}, store=BufferStore(tmp_path))
    out = rewrite_anywidget_html(_mount_in_cell(), anywidget_ctx=ctx)
    div = _mount_div(out)
    assert "data-buffers" not in div
    assert "data-css" not in div
    # No seeded state and no recorded state → marimo's model_id blob is kept as-is.
    assert json.loads(_attr(div, "data-initial-value")) == {"model_id": "m1"}


def test_cells_to_markdown_without_store_leaves_mounts_unbaked(tmp_path: Path) -> None:
    from marimo_book.transforms.marimo_export import ExportedNotebook

    exported = ExportedNotebook(
        source=tmp_path / "nb.py",
        cells=[
            {
                "cell_type": "code",
                "source": "w",
                "outputs": [{"output_type": "display_data", "data": {"text/html": _MOUNT}}],
            }
        ],
        metadata={},
        widget_states={"m1": WidgetModelState(state={"label": "k"}, buffers=[(["p"], b"z")])},
    )
    plain = cells_to_markdown(exported, hide_first_code_cell=False)
    assert "data-buffers" not in plain
    baked = cells_to_markdown(
        exported, hide_first_code_cell=False, buffer_store=BufferStore(tmp_path / "b")
    )
    assert "data-buffers" in baked and '"label": "k"' in baked


# --- end to end through marimo ------------------------------------------------


@pytest.fixture(scope="module")
def exported_fixture():
    pytest.importorskip("anywidget")
    return export_notebook(ANYWIDGET_NOTEBOOK, timeout=300)


def test_recorder_captures_state_for_the_ipynb_model_ids(exported_fixture) -> None:
    states = exported_fixture.widget_states
    assert states, "runner produced no widget states — did --states get written?"
    html_blob = json.dumps(exported_fixture.cells)
    assert "marimo-anywidget" in html_blob, "fixture output should contain a mount"
    # Same process, same run: the ids marimo wrote into the mounts are the
    # ids the recorder keyed its states by.
    ids_in_ipynb = {model_id for model_id in states if model_id in html_blob}
    assert len(ids_in_ipynb) == 1, (ids_in_ipynb, sorted(states))
    (model_id,) = ids_in_ipynb
    model = states[model_id]
    assert model.state["label"] == "from-kernel"
    assert model.state["scale"] == 2.5
    assert "_esm" not in model.state
    buffers = dict((tuple(p), b) for p, b in model.buffers)
    assert buffers[("payload",)] == bytes(range(256)) * 4
    assert buffers[("empty",)] == b""
    assert model.css and ".bytes-widget" in model.css


def _book_with_fixture(book_dir: Path) -> Book:
    (book_dir / "content").mkdir()
    shutil.copy(ANYWIDGET_NOTEBOOK, book_dir / "content" / "anywidget_notebook.py")
    (book_dir / "content" / "intro.md").write_text("# Intro\n", encoding="utf-8")
    return Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": False},
            "toc": [{"file": "content/intro.md"}, {"file": "content/anywidget_notebook.py"}],
        }
    )


def test_build_stages_buffers_and_replays_them_on_cache_hit(tmp_path: Path) -> None:
    pytest.importorskip("anywidget")
    book = _book_with_fixture(tmp_path)
    out_dir = tmp_path / "_site_src"
    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report.errors, report.errors

    page = (out_dir / "docs" / "anywidget_notebook.md").read_text(encoding="utf-8")
    div = _mount_div(page)
    assert '"label": "from-kernel"' in _attr(div, "data-initial-value")
    refs = json.loads(_attr(div, "data-buffers"))
    payload_ref = next(r for r in refs if r["path"] == ["payload"])
    digest = _sha(bytes(range(256)) * 4)
    assert payload_ref == {"path": ["payload"], "url": buffer_rel_url(digest), "size": 1024}
    staged_blob = out_dir / "docs" / BUFFER_URL_PREFIX / f"{digest}.bin"
    assert staged_blob.read_bytes() == bytes(range(256)) * 4
    assert _transient_buffer_store(tmp_path).has(digest)

    # Second build: cache hit must re-stage the blob into a wiped docs tree.
    shutil.rmtree(out_dir)
    report2 = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report2.errors, report2.errors
    assert report2.pages_cached == 1
    assert staged_blob.exists()

    # A pruned blob invalidates the hit instead of shipping a mount that 404s.
    _transient_buffer_store(tmp_path).path(digest).unlink()
    shutil.rmtree(out_dir)
    report3 = Preprocessor(book, book_dir=tmp_path).build(out_dir=out_dir)
    assert not report3.errors, report3.errors
    assert report3.pages_cached == 0  # the notebook re-executed
    assert staged_blob.exists()


def test_rendered_store_commits_buffers_and_tracks_them(tmp_path: Path) -> None:
    transient = BufferStore(tmp_path / "transient")
    digest = transient.put(b"committed-volume")
    body = f'<div data-buffers=\'[{{"path": ["p"], "url": "{buffer_rel_url(digest)}"}}]\'></div>'
    src = tmp_path / "nb.py"
    src.write_text("x = 1\n", encoding="utf-8")

    store = RenderedStore(tmp_path)
    store.write("nb.py", src, body, body_sig="sig", buffer_source=transient)
    store.save()
    assert store.buffer_store.has(digest)
    assert store.entries["nb.py"]["buffers"] == [digest]
    assert store.is_fresh("nb.py", src, body_sig="sig")

    store.buffer_store.path(digest).unlink()
    assert not store.is_fresh("nb.py", src, body_sig="sig")
    assert "buffer" in store.reason_stale("nb.py", src, body_sig="sig")


# --- helpers ------------------------------------------------------------------


def _mount_in_cell() -> str:
    return f"<marimo-ui-element object-id='m1' random-id='m1'>{_MOUNT}</marimo-ui-element>"


def _mount_div(html: str) -> str:
    m = re.search(r"<div class=\"marimo-book-anywidget\"[^>]*>", html)
    assert m, html
    return m.group(0)


def _attr(tag: str, name: str) -> str:
    import html as _html

    m = re.search(rf"{name}=(\"[^\"]*\"|'[^']*')", tag)
    assert m, (name, tag)
    return _html.unescape(m.group(1)[1:-1])


def test_precompute_splice_stages_buffers_referenced_only_by_deltas(tmp_path: Path) -> None:
    """The precompute splice writes the page directly (bypassing
    _finalize_page), so buffers that only the per-value deltas reference —
    a viewer whose volume changes with the slider — must be staged there too.
    """
    from unittest.mock import patch

    from marimo_book.transforms.precompute import PrecomputeResult
    from tests.test_precompute import _book_with_widget_notebook, _enable_precompute

    book = _enable_precompute(
        _book_with_widget_notebook(tmp_path, source="slider = mo.ui.slider(steps=[0, 1, 5])")
    )
    transient = _transient_buffer_store(tmp_path)
    digest = transient.put(b"per-value-volume")
    delta_ref = buffer_rel_url(digest)
    result = PrecomputeResult(
        body="<p>base</p>",
        widget_html=f'<script type="application/json">{{"1": "<div data-buffers=\'[{{\\"path\\": [\\"v\\"], \\"url\\": \\"{delta_ref}\\"}}]\'></div>"}}</script>',
        reactive_cell_indices=[1],
    )
    with patch("marimo_book.preprocessor.precompute_page", return_value=result):
        report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert not report.errors, report.errors
    assert report.widgets_precomputed == 1
    staged = tmp_path / "_site_src" / "docs" / BUFFER_URL_PREFIX / f"{digest}.bin"
    assert staged.read_bytes() == b"per-value-volume"

    # A delta referencing a blob the store lacks is a build error, not a 404.
    transient.path(digest).unlink()
    with patch("marimo_book.preprocessor.precompute_page", return_value=result):
        report2 = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src2")
    assert any("anywidget buffers missing" in e for e in report2.errors), report2.errors


def test_build_cache_does_not_prune_buffers_after_a_partial_scan(tmp_path: Path) -> None:
    """An OSError while scanning cached bodies must skip the blob prune —
    otherwise blobs still referenced by untouched bodies would be deleted."""
    from unittest.mock import patch

    from marimo_book.preprocessor import BuildCache

    book = Book.model_validate({"title": "T", "toc": [{"file": "content/nb.py"}]})
    (tmp_path / "content").mkdir()
    src = tmp_path / "content" / "nb.py"
    src.write_text("x = 1\n", encoding="utf-8")
    cache = BuildCache(tmp_path, book)
    digest = cache.buffer_store.put(b"still-referenced")
    cache.record(
        "content/nb.py",
        src,
        "nb.md",
        body=buffer_rel_url(digest),
        apply_rewrites=True,
        mode="static",
    )
    with patch.object(Path, "read_text", side_effect=OSError("disk went away")):
        cache.save()
    assert cache.buffer_store.has(digest)
    # A clean save still prunes what nothing references.
    orphan = cache.buffer_store.put(b"orphan")
    cache.dirty = True
    cache.save()
    assert cache.buffer_store.has(digest) and not cache.buffer_store.has(orphan)
