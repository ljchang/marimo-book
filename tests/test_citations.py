"""Tests for the native citations transform (transforms/citations.py)."""

from __future__ import annotations

import os
from pathlib import Path

BIB = """
@article{chang2015,
  author = {Chang, Luke J. and Smith, Alec},
  year = {2015},
  title = {Great paper},
  journal = {Nature},
  volume = {5},
  pages = {1--10},
  doi = {10.1000/x},
}
@book{doe2020,
  author = {Doe, Jane},
  year = {2020},
  title = {A Book},
  publisher = {MIT Press},
}
@inproceedings{trio2021,
  author = {Aa, A. and Bb, B. and Cc, C.},
  year = {2021},
  title = {Conference thing},
  booktitle = {Proc. of X},
  pages = {7--9},
}
"""


def _bib_file(tmp_path: Path) -> Path:
    f = tmp_path / "refs.bib"
    f.write_text(BIB, encoding="utf-8")
    return f


# --- loading ------------------------------------------------------------------


def test_load_bibliography_parses_and_memoizes(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import load_bibliography

    f = _bib_file(tmp_path)
    bib = load_bibliography((f,))
    assert set(bib) == {"chang2015", "doe2020", "trio2021"}
    assert load_bibliography((f,)) is bib  # same mtime → cached object

    # Touch with new content → reload.
    f.write_text(BIB + "\n@misc{new1, title={New}, year={2024}}\n", encoding="utf-8")
    os.utime(f, (f.stat().st_atime, f.stat().st_mtime + 5))
    bib2 = load_bibliography((f,))
    assert "new1" in bib2


def test_load_bibliography_skips_missing_files(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import load_bibliography

    assert load_bibliography((tmp_path / "gone.bib",)) == {}


# --- formatting ---------------------------------------------------------------


def test_format_entry_article(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import format_entry, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    text = format_entry(bib["chang2015"])
    # Fields are HTML-escaped for injection safety; &amp; renders as "&".
    assert "Chang, L. J., &amp; Smith, A." in text
    assert "(2015)" in text
    assert "*Nature*" in text
    assert "doi.org/10.1000/x" in text


def test_format_inline_apa_author_counts(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import format_inline_apa, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    assert format_inline_apa(bib["doe2020"]) == "(Doe, 2020)"
    assert format_inline_apa(bib["chang2015"]) == "(Chang & Smith, 2015)"
    assert format_inline_apa(bib["trio2021"]) == "(Aa et al., 2021)"


# --- page transform -------------------------------------------------------------


def test_apply_citations_apa_end_to_end(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "Emotion is neural [@chang2015]. See also [@doe2020; @trio2021].\n"
    out = apply_citations(body, bib=bib, style="apa")
    assert '(<a class="mb-cite" href="#mbref-chang2015">Chang &amp; Smith, 2015</a>)' in out
    assert "## References" in out
    assert 'id="mbref-doe2020"' in out
    assert out.index("chang2015") < out.index("## References")


def test_apply_citations_numbered_orders_by_first_use(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "First [@doe2020], then [@chang2015], then again [@doe2020].\n"
    out = apply_citations(body, bib=bib, style="numbered")
    assert '<a class="mb-cite" href="#mbref-doe2020">[1]</a>' in out
    assert '<a class="mb-cite" href="#mbref-chang2015">[2]</a>' in out
    refs = out[out.index("## References") :]
    assert refs.index("Doe") < refs.index("Chang")


def test_apply_citations_respects_code_regions(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "Real [@doe2020].\n```md\nexample [@chang2015]\n```\nInline `[@trio2021]` example.\n"
    out = apply_citations(body, bib=bib, style="numbered")
    assert "example [@chang2015]" in out  # fence untouched
    assert "`[@trio2021]`" in out  # span untouched
    refs = out[out.index("## References") :]
    assert "Chang" not in refs and "Aa" not in refs  # only the real citation listed


def test_apply_citations_bibliography_marker_controls_placement(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "Cite [@doe2020].\n\n\\bibliography\n\nAppendix follows.\n"
    out = apply_citations(body, bib=bib, style="apa")
    assert "\\bibliography" not in out
    assert out.index("## References") < out.index("Appendix follows.")


def test_apply_citations_unknown_key_left_verbatim(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "Known [@doe2020] and unknown [@nope].\n"
    out = apply_citations(body, bib=bib, style="apa")
    assert "[@nope]" in out


def test_apply_citations_no_citations_is_identity(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "No citations here.\n"
    assert apply_citations(body, bib=bib, style="apa") == body


def test_citation_like_link_labels_untouched(tmp_path: Path) -> None:
    """`[@handle](url)` is a markdown link with an @-label (GitHub-mention
    style), not a citation — it must survive verbatim even when the label
    matches a real bib key."""
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = "Thanks [@doe2020](https://github.com/doe2020)! But cite [@doe2020].\n"
    out = apply_citations(body, bib=bib, style="apa")
    assert "[@doe2020](https://github.com/doe2020)" in out
    assert "## References" in out  # the real citation still resolved


def test_citations_inside_html_pre_blocks_untouched(tmp_path: Path) -> None:
    """Notebook cell outputs land in the body as raw <pre> HTML, not fenced
    markdown — quoted [@key]s there are output text, not citations."""
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    body = 'Real [@doe2020].\n<pre class="marimo-stream-stdout">printed [@chang2015]</pre>\n'
    out = apply_citations(body, bib=bib, style="numbered")
    assert "printed [@chang2015]" in out
    refs = out[out.index("## References") :]
    assert "Chang" not in refs


def test_apa_multi_key_group_is_single_parenthetical(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    bib = load_bibliography((_bib_file(tmp_path),))
    out = apply_citations("See [@doe2020; @chang2015].\n", bib=bib, style="apa")
    assert ">Doe, 2020</a>; <a" in out  # one parenthetical, semicolon-joined
    assert "(<a" in out and out.count("(Doe") == 0


def test_latex_and_braces_cleaned_in_references(tmp_path: Path) -> None:
    from marimo_book.transforms.citations import apply_citations, load_bibliography

    f = tmp_path / "latex.bib"
    f.write_text(
        '@article{mueller2019, author={M\\"uller, Anna}, year={2019},\n'
        " title={The {Bayesian} Brain <test>}, journal={NeuroImage}}\n",
        encoding="utf-8",
    )
    bib = load_bibliography((f,))
    out = apply_citations("Cite [@mueller2019].\n", bib=bib, style="numbered")
    assert "Müller" in out
    assert "The Bayesian Brain" in out  # protector braces stripped
    assert "<test>" not in out and "&lt;test&gt;" in out  # fields HTML-escaped
