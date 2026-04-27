"""Tests for the static-reactivity precompute pipeline.

Phase 1+2 (AST scanner + cap preview) and Phase 3a (value substitution +
re-export with overrides) covered here. Phase 3b/3c (per-cell rendering
+ end-to-end lookup-table) tests live alongside.
"""

from __future__ import annotations

from marimo_book.transforms.precompute import (
    WidgetCandidate,
    estimate_combinations,
    page_excluded,
    scan_widgets,
    substitute_widget_value,
)


def _scan(src: str) -> list[WidgetCandidate]:
    return scan_widgets(src)


# --- slider ----------------------------------------------------------------


def test_slider_with_steps_kwarg() -> None:
    cands = _scan("slider = mo.ui.slider(steps=[0, 1, 5, 10])")
    assert len(cands) == 1
    c = cands[0]
    assert c.var_name == "slider" and c.kind == "slider"
    assert c.values == [0, 1, 5, 10]
    assert c.default == 0


def test_slider_with_explicit_step_kwarg() -> None:
    cands = _scan("s = mo.ui.slider(0, 10, step=2)")
    assert len(cands) == 1
    assert cands[0].values == [0, 2, 4, 6, 8, 10]


def test_slider_with_three_positional_args() -> None:
    cands = _scan("s = mo.ui.slider(0, 4, 1)")
    assert len(cands) == 1
    assert cands[0].values == [0, 1, 2, 3, 4]


def test_slider_continuous_no_step_is_skipped() -> None:
    """The user's rule: opt out continuous sliders unless an explicit grid."""
    assert _scan("s = mo.ui.slider(0, 10)") == []


def test_slider_with_float_step() -> None:
    cands = _scan("s = mo.ui.slider(0.0, 1.0, step=0.25)")
    assert len(cands) == 1
    assert cands[0].values == [0.0, 0.25, 0.5, 0.75, 1.0]


def test_slider_value_kwarg_sets_default() -> None:
    cands = _scan("s = mo.ui.slider(steps=[1, 2, 3], value=2)")
    assert cands[0].default == 2


def test_slider_non_literal_args_skipped() -> None:
    assert _scan("s = mo.ui.slider(low, high, step=1)") == []
    assert _scan("s = mo.ui.slider(steps=values)") == []


def test_slider_zero_step_skipped() -> None:
    assert _scan("s = mo.ui.slider(0, 10, step=0)") == []


def test_slider_with_all_kwargs() -> None:
    """marimo's recommended style: `slider(start=A, stop=B, step=N)`."""
    cands = _scan("s = mo.ui.slider(start=0, stop=10, step=2)")
    assert len(cands) == 1
    assert cands[0].values == [0, 2, 4, 6, 8, 10]


def test_slider_all_kwargs_no_step_is_continuous() -> None:
    assert _scan("s = mo.ui.slider(start=0, stop=10)") == []


def test_slider_all_kwargs_with_value_default() -> None:
    cands = _scan("s = mo.ui.slider(start=0, stop=4, step=1, value=2)")
    assert cands[0].values == [0, 1, 2, 3, 4]
    assert cands[0].default == 2


def test_slider_kwargs_with_extra_marimo_kwargs() -> None:
    """dartbrains-style: includes label, value, etc. We ignore the extras."""
    cands = _scan('s = mo.ui.slider(start=-15, stop=15, step=5, value=0, label="Translate X")')
    assert cands[0].values == [-15, -10, -5, 0, 5, 10, 15]


# --- dropdown --------------------------------------------------------------


def test_dropdown_with_list_options() -> None:
    cands = _scan('d = mo.ui.dropdown(options=["a", "b", "c"])')
    assert len(cands) == 1
    assert cands[0].kind == "dropdown" and cands[0].values == ["a", "b", "c"]
    assert cands[0].default == "a"


def test_dropdown_with_dict_options_uses_keys() -> None:
    cands = _scan('d = mo.ui.dropdown(options={"x": 1, "y": 2})')
    assert cands[0].values == ["x", "y"]


def test_dropdown_non_literal_options_skipped() -> None:
    assert _scan("d = mo.ui.dropdown(options=opts)") == []


# --- switch / checkbox ----------------------------------------------------


def test_switch_always_two_values() -> None:
    cands = _scan("s = mo.ui.switch()")
    assert cands[0].values == [True, False]


def test_checkbox_normalises_to_switch_kind() -> None:
    cands = _scan("c = mo.ui.checkbox()")
    assert cands[0].kind == "switch" and cands[0].values == [True, False]


# --- radio ----------------------------------------------------------------


def test_radio_with_list_options() -> None:
    cands = _scan('r = mo.ui.radio(options=["yes", "no"])')
    assert cands[0].kind == "radio" and cands[0].values == ["yes", "no"]


# --- skip cases -----------------------------------------------------------


def test_non_widget_calls_ignored() -> None:
    assert _scan("x = mo.md('hi')") == []
    assert _scan("y = pd.DataFrame()") == []
    assert _scan("z = list(range(10))") == []


def test_unsupported_widget_kinds_ignored() -> None:
    """range_slider deferred to v2; not a candidate yet."""
    assert _scan("r = mo.ui.range_slider(0, 10, step=1)") == []
    assert _scan("t = mo.ui.text(value='hi')") == []


def test_assignment_to_subscript_ignored() -> None:
    assert _scan("config['slider'] = mo.ui.slider(steps=[0, 1])") == []


def test_widget_inside_complex_expression_ignored() -> None:
    assert _scan("widgets = [mo.ui.slider(steps=[0, 1])]") == []


def test_syntax_error_returns_empty_not_raise() -> None:
    assert _scan("def broken(:") == []


# --- multiple widgets per page --------------------------------------------


def test_multiple_widgets_in_one_source() -> None:
    src = """
slider = mo.ui.slider(steps=[1, 2])
dropdown = mo.ui.dropdown(options=["a", "b", "c"])
switch = mo.ui.switch()
"""
    cands = _scan(src)
    kinds = sorted(c.kind for c in cands)
    assert kinds == ["dropdown", "slider", "switch"]


# --- helpers --------------------------------------------------------------


def test_estimate_combinations_is_cartesian_product() -> None:
    a = WidgetCandidate("a", "slider", [1, 2], 1, 1)
    b = WidgetCandidate("b", "dropdown", ["x", "y", "z"], "x", 2)
    assert estimate_combinations([a, b]) == 6
    assert estimate_combinations([]) == 1


def test_page_excluded_matches_normalised_path() -> None:
    assert page_excluded("content/heavy.py", ["content/heavy.py"]) is True
    assert page_excluded("content/heavy.py", ["content/light.py"]) is False
    assert page_excluded("content\\heavy.py", ["content/heavy.py"]) is True


# --- value substitution (Phase 3a) ----------------------------------------


def _single_cand(src: str) -> WidgetCandidate:
    cands = scan_widgets(src)
    assert len(cands) == 1
    return cands[0]


def test_substitute_appends_value_kwarg_when_absent() -> None:
    src = "slider = mo.ui.slider(steps=[0, 1, 5, 10])"
    out = substitute_widget_value(src, _single_cand(src), 5)
    assert "value=5" in out
    assert "steps=[0, 1, 5, 10]" in out


def test_substitute_replaces_existing_value_kwarg() -> None:
    src = "slider = mo.ui.slider(steps=[0, 1, 5, 10], value=1)"
    out = substitute_widget_value(src, _single_cand(src), 5)
    assert "value=5" in out
    assert "value=1" not in out


def test_substitute_preserves_surrounding_lines() -> None:
    src = "# comment\nslider = mo.ui.slider(steps=[0, 1, 5, 10])\n# trailing\n"
    out = substitute_widget_value(src, _single_cand(src), 5)
    assert out.startswith("# comment\n")
    assert out.rstrip().endswith("# trailing")


def test_substitute_dropdown_with_string_value() -> None:
    src = 'd = mo.ui.dropdown(options=["a", "b", "c"])'
    out = substitute_widget_value(src, _single_cand(src), "b")
    assert "value='b'" in out


def test_substitute_switch_with_bool() -> None:
    src = "s = mo.ui.switch()"
    out = substitute_widget_value(src, _single_cand(src), True)
    assert "value=True" in out


def test_substitute_handles_multi_line_call() -> None:
    """v2: multi-line widget calls are now supported via line-range splice."""
    src = "slider = mo.ui.slider(\n    steps=[0, 1, 5, 10],\n)"
    cand = _single_cand(src)
    out = substitute_widget_value(src, cand, 5)
    assert "value=5" in out
    # The original kwargs survive (steps list).
    assert "[0, 1, 5, 10]" in out
    # The result parses cleanly as Python.
    import ast as _ast

    _ast.parse(out)


def test_substitute_multi_line_preserves_surrounding_lines() -> None:
    src = (
        "x = 1\n"
        "slider = mo.ui.slider(\n"
        "    start=0,\n"
        "    stop=10,\n"
        "    step=2,\n"
        "    label='hi',\n"
        ")\n"
        "y = 2\n"
    )
    cand = _single_cand(src)
    out = substitute_widget_value(src, cand, 4)
    assert "value=4" in out
    assert out.startswith("x = 1\n")
    assert out.rstrip().endswith("y = 2")


def test_substitute_only_touches_target_call() -> None:
    """Two widgets on consecutive lines — only the targeted one should change."""
    src = "a = mo.ui.slider(steps=[0, 1])\nb = mo.ui.slider(steps=[10, 20])"
    cands = scan_widgets(src)
    out = substitute_widget_value(src, cands[1], 20)  # second slider
    a_line, b_line = out.split("\n")
    assert "value" not in a_line  # untouched
    assert "value=20" in b_line


# --- preview integration (Phase 2) ----------------------------------------
#
# These cover the inventory + cap-checking layer the preprocessor adds when
# `precompute.enabled: true`. They drive the full Preprocessor.build() so they
# share the marimo-export plumbing (1-2 s each).

from pathlib import Path  # noqa: E402

from marimo_book.config import Book  # noqa: E402
from marimo_book.preprocessor import Preprocessor  # noqa: E402


def _book_with_widget_notebook(book_dir: Path, *, source: str) -> Book:
    """Lay down a single-notebook book whose .py contains the given source."""
    content = book_dir / "content"
    content.mkdir(exist_ok=True)
    nb = content / "demo.py"
    nb.write_text(
        "import marimo\n"
        "\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n"
        "\n"
        "@app.cell\n"
        "def __():\n"
        "    import marimo as mo\n"
        "    return mo,\n"
        "\n"
        "@app.cell\n"
        f"def __(mo):\n"
        f"    {source}\n"
        "    return\n"
        "\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    return Book.model_validate({"title": "Test", "toc": [{"file": "content/demo.py"}]})


def _enable_precompute(book: Book, **overrides) -> Book:
    """Return a copy of `book` with precompute enabled + overrides applied."""
    payload = book.model_dump(mode="json")
    payload["precompute"] = {"enabled": True, **overrides}
    return Book.model_validate(payload)


def test_preview_counts_widgets_when_enabled(tmp_path: Path) -> None:
    book = _book_with_widget_notebook(tmp_path, source="slider = mo.ui.slider(steps=[0, 1, 5, 10])")
    book = _enable_precompute(book)

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 1
    assert report.widgets_skipped == 0


def test_preview_disabled_by_default(tmp_path: Path) -> None:
    book = _book_with_widget_notebook(tmp_path, source="slider = mo.ui.slider(steps=[0, 1, 5, 10])")

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 0


def test_preview_widget_over_max_values_skipped_with_warning(tmp_path: Path) -> None:
    big = ", ".join(str(i) for i in range(60))
    book = _book_with_widget_notebook(tmp_path, source=f"slider = mo.ui.slider(steps=[{big}])")
    book = _enable_precompute(book, max_values_per_widget=50)

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 1
    assert any("max_values_per_widget" in w for w in report.warnings)


def test_precompute_joint_widgets_via_cross_product(tmp_path: Path) -> None:
    """Widgets that share a downstream cell now cross-product together.

    Two sliders driving the same cell → joint group; lookup table is
    keyed by ``[a_value, b_value]`` JSON arrays.
    """
    content = tmp_path / "content"
    content.mkdir()
    nb = content / "demo.py"
    nb.write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    a = mo.ui.slider(steps=[1, 2])\n"
        "    return (a,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    b = mo.ui.slider(steps=[10, 20])\n"
        "    return (b,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, a, b):\n"
        # Cell reads from BOTH widgets — joint downstream.
        "    mo.md(f'a={a.value} b={b.value}')\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": True},
            "toc": [{"file": "content/demo.py"}],
        }
    )

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 2, report.warnings
    assert report.widgets_skipped == 0
    assert not report.errors

    staged = (tmp_path / "_site_src" / "docs" / "index.md").read_text(encoding="utf-8")
    # Joint group emits a single group metadata + lookup-table block.
    assert 'class="marimo-book-precompute-group"' in staged
    assert 'data-precompute-group="g0"' in staged
    # Both controls point at the same group.
    assert staged.count('data-precompute-group="g0"') >= 3  # 2 controls + group meta + table
    # Combo keys are JSON arrays of values.
    assert '"[2,10]"' in staged or '"[2, 10]"' in staged


def test_preview_single_widget_over_renders_cap_skips(tmp_path: Path) -> None:
    """A widget whose value count would push total renders past the cap."""
    # 20 values → 20 renders, on a 10-cap, with the widget cap raised so
    # that's not what trips.
    big = ", ".join(str(i) for i in range(20))
    book = _book_with_widget_notebook(tmp_path, source=f"slider = mo.ui.slider(steps=[{big}])")
    book = _enable_precompute(book, max_values_per_widget=50, max_combinations_per_page=10)

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 1
    assert any("max_combinations_per_page" in w for w in report.warnings)


def test_precompute_end_to_end_emits_lookup_table(tmp_path: Path) -> None:
    """Real precompute run should produce a lookup-table script + cell wrappers.

    Drives a tiny book through Preprocessor.build() with a widget whose
    downstream cell renders different markdown per value, and asserts the
    staged page contains the JS-discoverable markup.
    """
    content = tmp_path / "content"
    content.mkdir()
    nb = content / "demo.py"
    nb.write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    n = mo.ui.slider(steps=[1, 2, 3])\n"
        "    return (n,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, n):\n"
        "    mo.md(f'value is {n.value}')\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": True},
            "toc": [{"file": "content/demo.py"}],
        }
    )

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 1, report.warnings
    assert not report.errors

    staged = (tmp_path / "_site_src" / "docs" / "index.md").read_text(encoding="utf-8")
    assert 'class="marimo-book-precompute-control"' in staged
    assert 'data-precompute-widget="n"' in staged
    assert "data-precompute-cell=" in staged
    assert 'class="marimo-book-precompute-widget"' in staged
    assert 'class="marimo-book-precompute-table"' in staged
    # Lookup keys are JSON-stringified slider values; default (1) is omitted.
    assert '"2"' in staged
    assert '"3"' in staged


def test_precompute_joint_group_over_combinations_cap_skips(tmp_path: Path) -> None:
    """A joint group whose cartesian product exceeds the cap is rendered static."""
    content = tmp_path / "content"
    content.mkdir()
    nb = content / "demo.py"
    nb.write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    a = mo.ui.slider(steps=[1, 2, 3, 4, 5])\n"
        "    return (a,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    b = mo.ui.slider(steps=[10, 20, 30, 40, 50])\n"
        "    return (b,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, a, b):\n"
        "    mo.md(f'a={a.value} b={b.value}')\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            # 5 × 5 = 25 combos; cap at 10 → joint group skipped.
            "precompute": {"enabled": True, "max_combinations_per_page": 10},
            "toc": [{"file": "content/demo.py"}],
        }
    )

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert any("max_combinations_per_page" in w for w in report.warnings)


def test_precompute_two_independent_widgets(tmp_path: Path) -> None:
    """Two widgets controlling disjoint cells both precompute on one page."""
    content = tmp_path / "content"
    content.mkdir()
    nb = content / "demo.py"
    nb.write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    a = mo.ui.slider(steps=[1, 2])\n"
        "    return (a,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, a):\n"
        # Cell A: depends on `a` only.
        "    mo.md(f'A is {a.value}')\n"
        "    return\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    b = mo.ui.dropdown(options=['x', 'y'])\n"
        "    return (b,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, b):\n"
        # Cell B: depends on `b` only.
        "    mo.md(f'B is {b.value}')\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": True},
            "toc": [{"file": "content/demo.py"}],
        }
    )

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 2, report.warnings
    assert report.widgets_skipped == 0
    assert not report.errors

    staged = (tmp_path / "_site_src" / "docs" / "index.md").read_text(encoding="utf-8")
    # Both widgets get a control mount.
    assert 'data-precompute-widget="a"' in staged
    assert 'data-precompute-widget="b"' in staged
    # Both widgets have their own metadata + lookup-table script.
    assert staged.count('class="marimo-book-precompute-widget"') == 2
    assert staged.count('class="marimo-book-precompute-table"') == 2
    # Reactive cells tagged with the widget that drives them.
    assert "data-precompute-cell=" in staged


def test_diff_key_strips_stream_stderr_blocks() -> None:
    """``_diff_key`` removes ``<pre class="marimo-stream-stderr">…</pre>`` from
    cell bodies before comparing them, so non-deterministic warning text
    doesn't masquerade as a slider-driven output change.
    """
    from marimo_book.transforms.precompute import _diff_key

    body_a = (
        "```python\n"
        "data = load(...)\n"
        "```\n"
        '<pre class="marimo-stream-stderr">/runner/.venv/.../UserWarning: foo\n</pre>\n'
        "<div>hello</div>"
    )
    body_b = (
        "```python\n"
        "data = load(...)\n"
        "```\n"
        '<pre class="marimo-stream-stderr">/runner/.venv/.../UserWarning: bar\n</pre>\n'
        "<div>hello</div>"
    )
    assert _diff_key(body_a) == _diff_key(body_b)
    # And the result really has the stderr block stripped:
    assert "marimo-stream-stderr" not in _diff_key(body_a)
    assert "<div>hello</div>" in _diff_key(body_a)


def test_precompute_ignores_stderr_only_changes(tmp_path: Path) -> None:
    """Cells whose only difference across re-exports is non-deterministic
    stderr (warnings, runner-specific paths) must NOT be flagged as
    downstream of the precomputed widget.

    Reproduces the dartbrains ICA issue: data-load and persistent_cache
    cells emitted nltools UserWarnings with run-specific text. The diff
    detector treated each cell's body byte-for-byte and falsely tagged
    every upstream cell as ``data-precompute-cell``, so the slider
    mounted inline with the wrong cell.
    """
    content = tmp_path / "content"
    content.mkdir()
    nb = content / "demo.py"
    # Cell that emits a randomized warning to stderr each export — exactly
    # the non-determinism scenario the diff key normalization is supposed
    # to neutralize.
    nb.write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import sys, random\n"
        # Different stderr on each subprocess run: simulates a warning
        # whose body varies across exports.\n"
        "    sys.stderr.write(f'noise-{random.randint(0, 10**9)}\\n')\n"
        "    sys.stderr.flush()\n"
        "    return\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    n = mo.ui.slider(steps=[1, 2, 3])\n"
        "    return (n,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, n):\n"
        "    mo.md(f'value is {n.value}')\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": True},
            "toc": [{"file": "content/demo.py"}],
        }
    )

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 1, report.warnings
    assert not report.errors

    staged = (tmp_path / "_site_src" / "docs" / "index.md").read_text(encoding="utf-8")
    # Two cells flagged: the slider widget itself (its rendered HTML
    # changes with each value substitution) and the `mo.md(...)` cell that
    # consumes `n.value`. The noise cell — which only differs in its
    # stderr content across re-exports — must NOT be flagged.
    assert staged.count("data-precompute-cell=") == 2
    # The noise cell's stderr text appears in the page body (default value
    # rendered statically) but is not wrapped as reactive.
    assert "noise-" in staged
    # The reactive cell wrappers do NOT include the noise cell. Concretely,
    # walk the page and verify each `data-precompute-cell` block contains
    # either a `<marimo-slider>` element or the `value is <N>` text — not
    # a `noise-...` line.
    import re as _re

    cells_flagged = _re.findall(
        r'<div class="marimo-book-precompute-cell"[^>]*>(.*?)</div>',
        staged,
        flags=_re.DOTALL,
    )
    for body in cells_flagged:
        assert "noise-" not in body, "noise stderr cell should not be wrapped reactive"


def test_preview_excluded_page_is_silent(tmp_path: Path) -> None:
    book = _book_with_widget_notebook(tmp_path, source="slider = mo.ui.slider(steps=[0, 1, 5, 10])")
    book = _enable_precompute(book, exclude_pages=["content/demo.py"])

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 0
    assert not report.warnings


def test_split_extension_list_separates_strings_and_dicts() -> None:
    """The mkdocs-style mixed list flattens to Python-Markdown's two-arg shape."""
    from marimo_book.transforms.precompute import _split_extension_list

    names, configs = _split_extension_list(
        [
            "tables",
            "md_in_html",
            {"toc": {"permalink": True}},
            {"pymdownx.highlight": {"line_spans": "__span"}},
            {"pymdownx.betterem": {}},  # empty config dict — name kept, no config entry
        ]
    )
    assert names == [
        "tables",
        "md_in_html",
        "toc",
        "pymdownx.highlight",
        "pymdownx.betterem",
    ]
    assert configs == {
        "toc": {"permalink": True},
        "pymdownx.highlight": {"line_spans": "__span"},
    }


def test_precompute_lookup_table_values_are_rendered_html(tmp_path: Path) -> None:
    """Per-value lookup-table cells must contain HTML, not raw markdown.

    Regression test: the JS shim does ``el.innerHTML = delta[idx]``, so if
    the table stored markdown source the page would show ``\\`\\`\\`python
    …\\`\\`\\``` and ``| Scale | Value |`` literally when the user dragged
    the slider off its default value. We render each delta to HTML at build
    time using mkdocs's extension list so the swap produces correctly-styled
    cells that match the default-value cells mkdocs renders into the body.
    """
    import json
    import re

    content = tmp_path / "content"
    content.mkdir()
    nb = content / "demo.py"
    # Cell 2 emits a fenced code block + a markdown table — both pieces
    # whose markdown→HTML rendering is structurally distinct from the
    # markdown source (no false positives via substring overlap).
    nb.write_text(
        "import marimo\n\n"
        "__generated_with = '0.23.3'\n"
        "app = marimo.App()\n\n"
        "@app.cell(hide_code=True)\n"
        "def _():\n"
        "    import marimo as mo\n"
        "    return (mo,)\n\n"
        "@app.cell\n"
        "def _(mo):\n"
        "    n = mo.ui.slider(steps=[1, 2, 3])\n"
        "    return (n,)\n\n"
        "@app.cell(hide_code=True)\n"
        "def _(mo, n):\n"
        "    mo.md(f'| Scale | Value |\\n|---|---|\\n| n | **{n.value}** |')\n"
        "    return\n\n"
        'if __name__ == "__main__":\n'
        "    app.run()\n",
        encoding="utf-8",
    )
    book = Book.model_validate(
        {
            "title": "Test",
            "precompute": {"enabled": True},
            "toc": [{"file": "content/demo.py"}],
        }
    )

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 1, report.warnings

    staged = (tmp_path / "_site_src" / "docs" / "index.md").read_text(encoding="utf-8")
    match = re.search(
        r'<script type="application/json" class="marimo-book-precompute-table"[^>]*>'
        r"(.*?)</script>",
        staged,
        re.DOTALL,
    )
    assert match is not None, "lookup-table script not emitted"
    table = json.loads(match.group(1))
    # Values 2 and 3 are non-default; both should be HTML.
    assert {"2", "3"}.issubset(table.keys()), table.keys()
    for value_key, delta in table.items():
        joined = "\n".join(delta.values())
        # The slider cell (a fenced code block) renders via pymdownx.highlight.
        assert 'class="language-python highlight"' in joined, (
            f"value {value_key}: code block cell didn't render to highlight HTML, got: {joined!r}"
        )
        # The downstream cell (a markdown table) renders via the tables ext.
        assert "<table>" in joined, (
            f"value {value_key}: table cell didn't render to <table>, got: {joined!r}"
        )
        # Raw markdown table syntax must not survive into the lookup table.
        assert "|---|" not in joined, (
            f"value {value_key} still contains raw markdown table delimiters"
        )
