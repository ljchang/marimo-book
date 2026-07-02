"""Native pandoc-style citations for staged pages.

``[@key]`` / ``[@a; @b]`` in prose become linked inline citations plus a
per-page "References" section, resolved against the book's ``.bib`` files
(``bibliography.files``) in ``apa`` or ``numbered`` style (``cite_style``).

Deliberately NOT an mkdocs plugin: the obvious one (``mkdocs-bibtex``) was
archived in 2025 and requires system pandoc. Doing it in the preprocessor
keeps citations shell-agnostic (they'll survive the zensical migration) and
makes them work inside marimo notebook prose, which renders through the
same staged-markdown path as hand-written pages.

Applied at *finalize* time (see ``_finalize_page``), like link rewrites —
cached bodies keep the raw ``[@key]`` text, so editing a ``.bib`` file
takes effect on the next build without invalidating any notebook render.
"""

from __future__ import annotations

import html
import re
from pathlib import Path

from pybtex.database import Entry as _Entry
from pybtex.database import parse_file

# Pandoc-style citation group: [@key] or [@key1; @key2]. Keys are
# conservative (no spaces/brackets/semicolons) so prose like "[@ 4pm]"
# doesn't false-match.
_CITE_RE = re.compile(r"\[(@[^\s;\]]+(?:\s*;\s*@[^\s;\]]+)*)\]")

# Standalone placement marker (pandoc convention).
_MARKER_RE = re.compile(r"^\\bibliography\s*$", re.MULTILINE)

# Code regions are quoted syntax, not citations. Fences first (multiline),
# then inline spans within the remaining prose.
_CODE_FENCE_RE = re.compile(r"^(```|~~~).*?^\1\s*$", re.MULTILINE | re.DOTALL)
_CODE_SPAN_RE = re.compile(r"`[^`\n]*`")

# (files, mtimes) → parsed entries. One parse per build; serve rebuilds
# reload only when a .bib actually changes.
_BIB_CACHE: dict[tuple, dict[str, _Entry]] = {}


def load_bibliography(files: tuple[Path, ...]) -> dict[str, _Entry]:
    """Parse the book's ``.bib`` files into a key → entry map.

    Missing or unparsable files are skipped silently — ``marimo-book
    check`` is where they're reported; the build shouldn't crash over a
    bibliography typo.
    """
    stamped = []
    for f in files:
        try:
            stamped.append((str(f), f.stat().st_mtime))
        except OSError:
            continue
    cache_key = tuple(stamped)
    if cache_key in _BIB_CACHE:
        return _BIB_CACHE[cache_key]

    entries: dict[str, _Entry] = {}
    for path_str, _ in stamped:
        try:
            data = parse_file(path_str, bib_format="bibtex")
        except Exception:  # noqa: BLE001 — malformed .bib must not kill the build
            continue
        entries.update(data.entries)
    _BIB_CACHE[cache_key] = entries
    return entries


# --- formatting ---------------------------------------------------------------


def _person_apa(person) -> str:
    """``Chang, L. J.`` from a pybtex Person."""
    last = " ".join(person.prelast_names + person.last_names)
    initials = " ".join(
        f"{n[0]}." for part in (person.first_names, person.middle_names) for n in part if n
    )
    return f"{last}, {initials}".strip().rstrip(",")


def _authors_apa(entry: _Entry) -> str:
    people = entry.persons.get("author") or entry.persons.get("editor") or []
    names = [_person_apa(p) for p in people]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    return ", ".join(names[:-1]) + f", & {names[-1]}"


def _last_name(person) -> str:
    return " ".join(person.prelast_names + person.last_names)


def format_inline_apa(entry: _Entry) -> str:
    """``(Chang & Smith, 2015)`` — 1 / 2 / et-al author forms."""
    people = entry.persons.get("author") or entry.persons.get("editor") or []
    year = entry.fields.get("year", "n.d.")
    if not people:
        return f"({entry.fields.get('title', '?')}, {year})"
    if len(people) == 1:
        who = _last_name(people[0])
    elif len(people) == 2:
        who = f"{_last_name(people[0])} & {_last_name(people[1])}"
    else:
        who = f"{_last_name(people[0])} et al."
    return f"({who}, {year})"


def format_entry(entry: _Entry) -> str:
    """APA-flavored one-line reference; shared by both styles."""
    f = entry.fields
    authors = _authors_apa(entry)
    year = f.get("year", "n.d.")
    title = f.get("title", "").strip("{}")
    parts = [f"{authors} ({year}). {title}." if authors else f"{title} ({year})."]

    if entry.type == "article":
        venue = f.get("journal", "")
        vol = f.get("volume", "")
        pages = f.get("pages", "").replace("--", "–")
        bits = f"*{venue}*" if venue else ""
        if vol:
            bits += f", {vol}"
        if pages:
            bits += f", {pages}"
        if bits:
            parts.append(f"{bits}.")
    elif entry.type == "book":
        if f.get("publisher"):
            parts.append(f"{f['publisher']}.")
    elif entry.type == "inproceedings":
        venue = f.get("booktitle", "")
        pages = f.get("pages", "").replace("--", "–")
        if venue:
            parts.append(f"In *{venue}*" + (f" (pp. {pages})." if pages else "."))

    if f.get("doi"):
        parts.append(f"https://doi.org/{f['doi']}")
    elif f.get("url"):
        parts.append(f.get("url", ""))
    return " ".join(p for p in parts if p)


# --- page transform -------------------------------------------------------------


def apply_citations(body: str, *, bib: dict[str, _Entry], style: str) -> str:
    """Resolve ``[@key]`` groups in prose and emit a References section.

    Unknown keys stay verbatim (visible in the page; ``check`` warns).
    Returns the body unchanged when nothing resolves.
    """
    cited: list[str] = []  # keys in first-use order

    def _render_group(match: re.Match) -> str:
        rendered = []
        unknown = []
        for raw in match.group(1).split(";"):
            key = raw.strip().lstrip("@")
            entry = bib.get(key)
            if entry is None:
                unknown.append(f"@{key}")
                continue
            if key not in cited:
                cited.append(key)
            if style == "numbered":
                label = f"[{cited.index(key) + 1}]"
            else:
                label = html.escape(format_inline_apa(entry))
            rendered.append(f'<a class="mb-cite" href="#mbref-{key}">{label}</a>')
        out = ", ".join(rendered)
        if unknown:  # keep unresolved keys visible, pandoc-style
            out = f"{out} [{'; '.join(unknown)}]" if out else match.group(0)
        return out

    # Transform prose only: split out fences, then inline spans.
    def _transform_prose(text: str) -> str:
        pieces: list[str] = []
        pos = 0
        for span in _CODE_SPAN_RE.finditer(text):
            pieces.append(_CITE_RE.sub(_render_group, text[pos : span.start()]))
            pieces.append(span.group(0))
            pos = span.end()
        pieces.append(_CITE_RE.sub(_render_group, text[pos:]))
        return "".join(pieces)

    pieces: list[str] = []
    pos = 0
    for fence in _CODE_FENCE_RE.finditer(body):
        pieces.append(_transform_prose(body[pos : fence.start()]))
        pieces.append(fence.group(0))
        pos = fence.end()
    pieces.append(_transform_prose(body[pos:]))
    out = "".join(pieces)

    if not cited:
        return body if not _MARKER_RE.search(body) else _MARKER_RE.sub("", body)

    if style == "numbered":
        keys = cited  # first-use order
    else:
        keys = sorted(cited, key=lambda k: (_authors_apa(bib[k]) or "￿", k))
    items = []
    for i, key in enumerate(keys, 1):
        prefix = f"{i}. " if style == "numbered" else "- "
        items.append(f'{prefix}<span id="mbref-{key}"></span>{format_entry(bib[key])}')
    references = "## References\n\n" + "\n".join(items) + "\n"

    if _MARKER_RE.search(out):
        return _MARKER_RE.sub(lambda _m: references.rstrip("\n"), out, count=1)
    return out.rstrip("\n") + "\n\n" + references
