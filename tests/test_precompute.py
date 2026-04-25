"""Tests for the static-reactivity widget detection (Phase 1).

These cover the AST scanner only — no actual notebook execution. The
re-export + lookup-table pipeline has its own end-to-end tests once
Phase 3 lands.
"""

from __future__ import annotations

from marimo_book.transforms.precompute import (
    WidgetCandidate,
    estimate_combinations,
    page_excluded,
    scan_widgets,
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


def test_preview_page_over_max_combinations_skips_all(tmp_path: Path) -> None:
    # 11 × 11 × 11 = 1331 combinations on a low cap of 100.
    book = _book_with_widget_notebook(
        tmp_path,
        source="\n    ".join(
            [
                "a = mo.ui.slider(0, 10, step=1)",
                "b = mo.ui.slider(0, 10, step=1)",
                "c = mo.ui.slider(0, 10, step=1)",
            ]
        ),
    )
    book = _enable_precompute(book, max_combinations_per_page=100)

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 3
    assert any("max_combinations_per_page" in w for w in report.warnings)


def test_preview_excluded_page_is_silent(tmp_path: Path) -> None:
    book = _book_with_widget_notebook(tmp_path, source="slider = mo.ui.slider(steps=[0, 1, 5, 10])")
    book = _enable_precompute(book, exclude_pages=["content/demo.py"])

    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=tmp_path / "_site_src")
    assert report.widgets_precomputed == 0
    assert report.widgets_skipped == 0
    assert not report.warnings
