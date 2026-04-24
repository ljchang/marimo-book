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
from typing import Annotated, Any, Literal, Union

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


class Analytics(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["plausible", "google", "none"] = "none"
    property: str | None = None


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
    children: list["TocEntry"] = Field(default_factory=list)


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
    Union[
        Annotated[FileEntry, Tag("file")],
        Annotated[UrlEntry, Tag("url")],
        Annotated[SectionEntry, Tag("section")],
    ],
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

    # render defaults
    defaults: Defaults = Field(default_factory=Defaults)

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
