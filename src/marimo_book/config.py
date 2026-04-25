"""Pydantic v2 schema for ``book.yml``.

The single source of truth for a marimo-book configuration. Loading a
``book.yml`` through :func:`load_book` validates the document and returns a
fully-typed :class:`Book` instance.

The TOC uses a discriminated union over three entry shapes:

- :class:`FileEntry`    — a local ``.md`` or marimo ``.py`` file
- :class:`UrlEntry`     — an external link rendered in the sidebar
- :class:`SectionEntry` — a grouping with nested children (recursive)

The discriminator inspects which key is present (``file``, ``url``, or
``section``) so the YAML stays key-driven rather than requiring an explicit
``type:`` tag per entry.
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import BaseModel, ConfigDict, Discriminator, Field, Tag, field_validator

# --- leaf models -------------------------------------------------------------


class Author(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    orcid: str | None = None
    affiliation: str | None = None
    email: str | None = None


class Palette(BaseModel):
    model_config = ConfigDict(extra="forbid")

    primary: str | None = None
    accent: str | None = None


class Font(BaseModel):
    model_config = ConfigDict(extra="forbid")

    text: str | None = None
    code: str | None = None


class Theme(BaseModel):
    model_config = ConfigDict(extra="forbid")

    palette: Palette = Field(default_factory=Palette)
    font: Font = Field(default_factory=Font)


class LaunchButtons(BaseModel):
    """Per-chapter buttons injected by the preprocessor.

    v0.1 ships ``molab``, ``github``, ``download``. Other fields are reserved
    flags so users can toggle them in config without schema changes when v0.2
    lands (``wasm``) or if we decide to support ``colab`` / ``binder`` later.
    """

    model_config = ConfigDict(extra="forbid")

    molab: bool = True
    github: bool = True
    download: bool = True
    colab: bool = False
    binder: bool = False
    wasm: bool = False  # v0.2


class Bibliography(BaseModel):
    model_config = ConfigDict(extra="forbid")

    files: list[Path] = Field(default_factory=list)


class Precompute(BaseModel):
    """Static-reactivity opt-in for discrete marimo UI widgets.

    When ``enabled`` is true, the preprocessor scans each ``.py`` page
    for widget calls whose value set is statically determinable
    (``mo.ui.slider`` with ``steps=[...]`` or explicit ``step=N``,
    ``mo.ui.dropdown``, ``mo.ui.switch``, ``mo.ui.radio``). For each
    candidate it re-runs ``marimo export`` once per value (or per
    cartesian combination across widgets sharing a downstream subgraph)
    and embeds a JSON lookup table in the rendered page. A small JS
    shim swaps the visible output as the reader interacts with the
    widget — real-feeling interactivity without a Python kernel.

    Caps protect against pathological cases. Widgets / pages that
    exceed any cap are gracefully skipped (rendered static, with a
    ``BuildReport.warnings`` entry); the build does not fail unless
    you pass ``--strict``.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False

    # Hard count caps — checked before any execution starts. Cheap.
    max_values_per_widget: int = Field(default=50, ge=1)
    max_combinations_per_page: int = Field(default=200, ge=1)

    # Wall-clock budget per page — checked after the first re-export
    # completes. If `first_export_seconds * remaining_combinations` would
    # exceed this, the rest of the page's precompute is aborted and the
    # page renders static at default values. The first export is *always*
    # paid (we need it as the static fallback anyway), so very small
    # budgets just mean "skip precompute, render static".
    max_seconds_per_page: int = Field(default=60, ge=1)

    # Bundle-size cap — checked after each combination's output is
    # captured. Aborts further precompute when total embedded bytes for
    # the page would exceed.
    max_bytes_per_page: int = Field(default=10 * 1024 * 1024, ge=1024)

    # Per-page opt-out. Pages listed here render every widget as static
    # even when `enabled: true`.
    exclude_pages: list[str] = Field(default_factory=list)


class Analytics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["plausible", "google", "none"] = "none"
    property: str | None = None


class Dependencies(BaseModel):
    """How notebooks get their Python dependencies at build time.

    - ``env`` (default) — reuse the Python environment that invoked
      ``marimo-book``. The consuming project is expected to pin its
      notebook deps in its own ``pyproject.toml`` / ``requirements.txt``
      and install them before running a build. This is the fastest mode
      (no venv provisioning per notebook).
    - ``sandbox`` — pass ``--sandbox`` to ``marimo export ipynb``. Marimo
      then provisions an isolated ``uv`` environment per notebook from
      the notebook's PEP 723 inline metadata
      (``# /// script\\n# dependencies = [...]\\n# ///``). Slower on first
      run (~5–10s to resolve) but reproducible and self-contained;
      notebooks become portable to any machine with ``uv`` installed.

    The CLI ``--sandbox`` / ``--no-sandbox`` flags on ``build`` and
    ``serve`` override this per-invocation.
    """

    model_config = ConfigDict(extra="forbid")

    mode: Literal["env", "sandbox"] = "env"


class Defaults(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mode: Literal["static"] = "static"  # v0.2 adds "wasm", "hybrid"
    hide_author_line: bool = True
    show_source_link: bool = True
    # The first code cell in a marimo notebook is, by convention, the setup /
    # imports cell. Most notebooks author it as ``@app.cell`` (not
    # ``hide_code=True``), but it's almost never part of the lesson. Drop it
    # unconditionally by default; authors can opt out per-book.
    hide_first_code_cell: bool = True


# --- TOC entries (discriminated union) ---------------------------------------


class FileEntry(BaseModel):
    """A content page backed by a local ``.md`` or marimo ``.py`` file."""

    model_config = ConfigDict(extra="forbid")

    file: Path
    title: str | None = None
    mode: Literal["static"] = "static"  # v0.2 adds "wasm", "hybrid"
    hidden: bool = False


class UrlEntry(BaseModel):
    """An external link that appears in the sidebar."""

    model_config = ConfigDict(extra="forbid")

    url: str
    title: str


class SectionEntry(BaseModel):
    """A grouping node. Recursive via ``children``."""

    model_config = ConfigDict(extra="forbid")

    section: str
    children: list[TocEntry] = Field(default_factory=list)


def _entry_discriminator(v: Any) -> str | None:
    """Pick the entry variant by the unique key present in the mapping."""
    if isinstance(v, dict):
        if "file" in v:
            return "file"
        if "url" in v:
            return "url"
        if "section" in v:
            return "section"
    else:
        # already a model instance
        if isinstance(v, FileEntry):
            return "file"
        if isinstance(v, UrlEntry):
            return "url"
        if isinstance(v, SectionEntry):
            return "section"
    return None


TocEntry = Annotated[
    Annotated[FileEntry, Tag("file")]
    | Annotated[UrlEntry, Tag("url")]
    | Annotated[SectionEntry, Tag("section")],
    Discriminator(_entry_discriminator),
]

SectionEntry.model_rebuild()


# --- top-level Book model ----------------------------------------------------


class Book(BaseModel):
    """Validated ``book.yml``.

    A new book requires only ``title`` and ``toc``; everything else has
    sensible defaults. Unknown top-level keys are rejected so typos surface
    during ``marimo-book check``.
    """

    model_config = ConfigDict(extra="forbid")

    # metadata
    title: str
    description: str | None = None
    authors: list[Author] = Field(default_factory=list)
    copyright: str | None = None
    license: str | None = None
    repo: str | None = None
    branch: str = "main"
    doi: str | None = None
    # Canonical public URL where this book is (or will be) hosted. Used by
    # mkdocs as ``site_url`` so the social plugin can emit fully-qualified
    # OpenGraph URLs, sitemap.xml gets the right href, etc.
    url: str | None = None

    # branding
    logo: Path | None = None
    favicon: Path | None = None
    theme: Theme = Field(default_factory=Theme)

    # per-chapter buttons (can be overridden on an entry-by-entry basis later)
    launch_buttons: LaunchButtons = Field(default_factory=LaunchButtons)

    # bibliography
    bibliography: Bibliography = Field(default_factory=Bibliography)
    cite_style: Literal["apa", "numbered"] = "apa"

    # analytics
    analytics: Analytics = Field(default_factory=Analytics)

    # How notebook dependencies get provisioned at build time. See the
    # :class:`Dependencies` docstring for the tradeoffs.
    dependencies: Dependencies = Field(default_factory=Dependencies)

    # Opt-in external-link checker. When true, the generated mkdocs.yml adds
    # the ``htmlproofer`` plugin, which HEAD-checks every <a href> and
    # <img src> at build time against the live web. Slow; keep off in CI
    # unless you have a reason. Requires: ``pip install marimo-book[linkcheck]``.
    check_external_links: bool = False

    # Opt-in social / OpenGraph card generation. When true, the generated
    # mkdocs.yml adds Material's ``social`` plugin, which renders a PNG
    # social preview per page and injects the matching ``<meta>`` tags.
    # Requires: ``pip install marimo-book[social]``.
    social_cards: bool = False

    # Opt-in cross-reference resolution by heading text — the MkDocs analog
    # of MyST ``{ref}``. When true, the generated mkdocs.yml adds the
    # ``autorefs`` plugin so authors can write ``[Heading text][]`` and have
    # it resolve to whatever page contains that heading. Headings on the
    # same page already resolve via Material's standard anchor IDs; this
    # flag enables the cross-page case. Requires:
    # ``pip install marimo-book[autorefs]``.
    cross_references: bool = False

    # When true, the preprocessor copies ``CHANGELOG.md`` from the book
    # root into the staged docs tree and appends a ``Changelog`` entry
    # to the nav. Lets you maintain a single CHANGELOG.md at the repo
    # root (canonical PyPI convention) while still surfacing it in the
    # rendered book. No-op if no ``CHANGELOG.md`` exists.
    include_changelog: bool = False

    # Opt-in single-PDF export of the entire book. When true, the
    # generated mkdocs.yml adds the ``with-pdf`` plugin which renders
    # the site through WeasyPrint into ``_site/pdf/<title>.pdf`` and
    # injects a download link into the page footer. Slow on large books
    # (~30 s for ~50 pages); turn off in ``serve`` and on in CI / for
    # release builds. Requires: ``pip install marimo-book[pdf]``.
    pdf_export: bool = False

    # Opt-in static reactivity for marimo UI elements. When enabled, the
    # preprocessor scans each ``.py`` page for discrete widget candidates
    # (``mo.ui.slider`` with explicit ``steps=[]`` or ``step=N``,
    # ``mo.ui.dropdown``, ``mo.ui.switch``, ``mo.ui.radio``) and re-runs
    # ``marimo export`` once per value, embedding the results as a
    # client-side lookup table. A small JS shim binds the widget input to
    # swap the visible output without a Python kernel.
    precompute: Precompute = Field(default_factory=lambda: Precompute())

    # render defaults
    defaults: Defaults = Field(default_factory=Defaults)

    # Optional per-widget-class default state. These seed the model that
    # backs each anywidget mount, so widgets whose JS reads
    # ``model.get("key")`` without a fallback still render correctly on the
    # static site. Literal kwargs harvested from each cell override these
    # defaults; whatever the widget's JS needs but neither source supplies
    # stays undefined (and should be guarded client-side).
    widget_defaults: dict[str, dict[str, object]] = Field(default_factory=dict)

    # TOC
    toc: list[TocEntry]

    # shell
    shell: Literal["mkdocs"] = "mkdocs"  # v0.3 adds "zensical", "jinja"

    @field_validator("bibliography", mode="before")
    @classmethod
    def _coerce_bibliography(cls, v: Any) -> Any:
        """Allow ``bibliography: [path1, path2]`` shorthand in YAML."""
        if isinstance(v, list):
            return {"files": v}
        return v


# --- loader ------------------------------------------------------------------


def load_book(path: str | Path) -> Book:
    """Read and validate a ``book.yml`` file.

    Raises ``pydantic.ValidationError`` with a field-aware message on failure.
    """
    path = Path(path)
    with path.open("r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    if data is None:
        raise ValueError(f"{path} is empty")
    return Book.model_validate(data)
