"""Where a page's assignment notebook comes from.

Two forms of ``assignment:`` on a TOC entry:

``assignment: content/assignments/glm.py``
    A file in the book, used as-is. The original form: a copy of the student
    notebook the grader published, committed into the book.

``assignment: glm``
    A slug, resolved against the book's ``grader:`` section to the notebook
    the grader currently publishes::

        {server}/a/{course}/{term}/{slug}/student.py

    Fetched at build time into ``.marimo_book_cache/assignments/`` so the
    grader stays the single source of truth: a republish reaches the site on
    the next build with nothing to commit. If the grader cannot be reached
    and a cached copy exists, the build uses the copy and says so; with no
    copy either, it fails rather than publish a page whose assignment is
    missing.

The same ``grader:`` section is what ``sync-deps`` writes into every
chapter's PEP 723 block as ``[tool.grader]``, so a notebook opened in molab
or on a laptop knows which grader, course and term it belongs to without
any of that being hardcoded in the notebook.
"""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

from .config import Book, FileEntry

CACHE_SUBDIR = Path(".marimo_book_cache") / "assignments"


class AssignmentError(ValueError):
    pass


@dataclass(frozen=True)
class Assignment:
    src: Path  # the notebook to stage, absolute
    rel: Path  # the TOC-relative name the staged copy is published under
    slug: str | None = None  # set when grader-sourced
    student_url: str | None = None
    molab_url: str | None = None
    version: str | None = None  # X-Grader-Version of the fetched copy
    notes: tuple[str, ...] = field(default=())  # things a check should surface as warnings


def is_slug(value: Path | str) -> bool:
    """A bare name: no directory, no extension. Anything else is a file path."""
    p = Path(value)
    return len(p.parts) == 1 and p.suffix == "" and p.name not in ("", ".", "..")


def grader_urls(book: Book, slug: str) -> tuple[str, str]:
    """``(student.py url, molab url)`` for ``slug`` under the book's grader."""
    if book.grader is None:
        raise AssignmentError(
            f"assignment {slug!r} is a grader slug, but book.yml has no `grader:` section "
            "(server, course, term)"
        )
    g = book.grader
    base = f"{g.server.rstrip('/')}/a/{g.course}/{g.term}/{slug}"
    return f"{base}/student.py", f"{base}/molab"


def _download(url: str, *, timeout: float = 30) -> tuple[bytes, dict[str, str]]:
    """GET ``url``; return ``(body, headers)``. Separate so tests can replace it."""
    req = urllib.request.Request(url, headers={"Accept": "text/x-python, */*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(), {k.lower(): v for k, v in r.headers.items()}


def resolve_assignment(
    entry: FileEntry, book: Book, book_dir: Path, *, fetch: bool = True
) -> Assignment:
    """The notebook behind ``entry.assignment``; see the module docstring."""
    if entry.assignment is None:
        raise AssignmentError("entry has no assignment")
    value = entry.assignment
    local = (book_dir / value).resolve()
    if local.exists():
        return Assignment(src=local, rel=Path(value))
    if not is_slug(value):
        raise AssignmentError(f"assignment references a missing file ({value})")

    slug = Path(value).name
    student_url, molab_url = grader_urls(book, slug)
    g = book.grader
    assert g is not None
    cache = book_dir / CACHE_SUBDIR / g.course / g.term / f"{slug}.py"
    version_file = cache.with_suffix(".version")
    rel = Path("assignments") / f"{slug}.py"
    notes: list[str] = []
    version: str | None = None

    if fetch:
        try:
            body, headers = _download(student_url)
        except (urllib.error.URLError, urllib.error.HTTPError, OSError, TimeoutError) as e:
            reason = getattr(e, "reason", None) or getattr(e, "code", None) or e
            if not cache.exists():
                raise AssignmentError(
                    f"could not fetch assignment {slug!r} from {student_url} ({reason}) "
                    "and no cached copy exists"
                ) from e
            notes.append(
                f"assignment {slug!r}: grader unreachable ({reason}); "
                f"using the cached copy at {cache.relative_to(book_dir)}"
            )
        else:
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_bytes(body)
            version = headers.get("x-grader-version")
            if version:
                version_file.write_text(version, encoding="utf-8")
            else:
                version_file.unlink(missing_ok=True)
    elif not cache.exists():
        raise AssignmentError(
            f"assignment {slug!r} has not been fetched from {student_url} yet (no cached copy)"
        )

    if version is None and version_file.exists():
        version = version_file.read_text(encoding="utf-8").strip() or None
    return Assignment(
        src=cache,
        rel=rel,
        slug=slug,
        student_url=student_url,
        molab_url=molab_url,
        version=version,
        notes=tuple(notes),
    )
