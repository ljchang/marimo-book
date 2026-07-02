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

import codecs
import html
import re
from pathlib import Path

import latexcodec  # noqa: F401 — registers the "ulatex" codec used by _clean
from pybtex.database import Entry as _Entry
from pybtex.database import parse_file

# Pandoc-style citation group: [@key] or [@key1; @key2]. Keys are
# conservative (no spaces/brackets/semicolons) so prose like "[@ 4pm]"
# doesn't false-match, and the negative lookahead skips markdown links
# whose *label* looks like a citation — `[@handle](https://...)`, the
# common GitHub-mention pattern.
_CITE_RE = re.compile(r"\[(@[^\s;\]]+(?:\s*;\s*@[^\s;\]]+)*)\](?!\()")

# Standalone placement marker (pandoc convention). `[ \t]*` — not `\s*` —
# so the match stops at the line's own end and doesn't swallow the blank
# line separating the marker from the content below it.
_MARKER_RE = re.compile(r"^\\bibliography[ \t]*$", re.MULTILINE)

# Regions whose text is quoted, not prose: fenced blocks (indentation
# allowed — lists/admonitions), double- or single-backtick spans, and raw
# HTML <pre> blocks (marimo cell outputs land in the body as _html_pre
# HTML, not fenced markdown). Fences first, then the rest within prose.
_CODE_FENCE_RE = re.compile(r"^[ \t]*(```|~~~).*?^[ \t]*\1[ \t]*$", re.MULTILINE | re.DOTALL)
_CODE_SPAN_RE = re.compile(r"``[^`]*``|`[^`\n]*`")
_HTML_PRE_RE = re.compile(r"<pre\b.*?</pre>", re.DOTALL | re.IGNORECASE)

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
    if len(_BIB_CACHE) > 8:
        # Long `serve` sessions mint a new key per .bib edit; don't let
        # superseded parses accumulate forever.
        _BIB_CACHE.clear()

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


def _clean(value: str) -> str:
    """BibTeX field → display text: decode LaTeX, drop braces, escape HTML.

    Braces are BibTeX capitalization protectors ({AI}, {Bayesian}) — plain
    removal is the standard display treatment. HTML-escaping keeps .bib
    content from injecting markup into the page (the inline labels are
    escaped at the call site; entry fields are escaped here).
    """
    try:
        value = codecs.decode(value, "ulatex")
    except Exception:  # noqa: BLE001 — odd escapes render as-is, not fatally
        pass
    return html.escape(value.replace("{", "").replace("}", ""))


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
    authors = _clean(_authors_apa(entry))
    year = _clean(f.get("year", "n.d."))
    title = _clean(f.get("title", ""))
    parts = [f"{authors} ({year}). {title}." if authors else f"{title} ({year})."]

    if entry.type == "article":
        venue = _clean(f.get("journal", ""))
        vol = _clean(f.get("volume", ""))
        pages = _clean(f.get("pages", "")).replace("--", "–")
        bits = f"*{venue}*" if venue else ""
        if vol:
            bits += f", {vol}"
        if pages:
            bits += f", {pages}"
        if bits:
            parts.append(f"{bits}.")
    elif entry.type == "book":
        if f.get("publisher"):
            parts.append(f"{_clean(f['publisher'])}.")
    elif entry.type == "inproceedings":
        venue = _clean(f.get("booktitle", ""))
        pages = _clean(f.get("pages", "")).replace("--", "–")
        if venue:
            parts.append(f"In *{venue}*" + (f" (pp. {pages})." if pages else "."))

    if f.get("doi"):
        parts.append(f"https://doi.org/{_clean(f['doi'])}")
    elif f.get("url"):
        parts.append(_clean(f.get("url", "")))
    return " ".join(p for p in parts if p)


# --- page transform -------------------------------------------------------------


def apply_citations(body: str, *, bib: dict[str, _Entry], style: str) -> str:
    """Resolve ``[@key]`` groups in prose and emit a References section.

    Unknown keys stay verbatim (visible in the page; ``check`` warns).
    Returns the body unchanged when nothing resolves.
    """
    cited: list[str] = []  # keys in first-use order

    def _render_group(match: re.Match) -> str:
        anchors = []
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
                # Strip the parens: an APA group is ONE parenthetical with
                # its members joined by semicolons — (A, 2015; B, 2020).
                label = html.escape(format_inline_apa(entry)[1:-1])
            anchors.append(f'<a class="mb-cite" href="#mbref-{key}">{label}</a>')
        if style == "numbered":
            out = ", ".join(anchors)
        else:
            out = f"({'; '.join(anchors)})" if anchors else ""
        if unknown:  # keep unresolved keys visible, pandoc-style
            out = f"{out} [{'; '.join(unknown)}]" if out else match.group(0)
        return out

    def _sub_protected(text: str, protect: list[re.Pattern], leaf) -> str:
        """Apply ``leaf`` only outside the first pattern's matches, recursing
        through the remaining patterns inside the unprotected gaps."""
        if not protect:
            return leaf(text)
        head, rest = protect[0], protect[1:]
        pieces: list[str] = []
        pos = 0
        for m in head.finditer(text):
            pieces.append(_sub_protected(text[pos : m.start()], rest, leaf))
            pieces.append(m.group(0))
            pos = m.end()
        pieces.append(_sub_protected(text[pos:], rest, leaf))
        return "".join(pieces)

    out = _sub_protected(
        body,
        [_CODE_FENCE_RE, _HTML_PRE_RE, _CODE_SPAN_RE],
        lambda t: _CITE_RE.sub(_render_group, t),
    )

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
        # First marker gets the section; any extras are stripped (matching
        # the strip-all behavior of the no-citations path).
        out = _MARKER_RE.sub(lambda _m: references.rstrip("\n"), out, count=1)
        return _MARKER_RE.sub("", out)
    return out.rstrip("\n") + "\n\n" + references
