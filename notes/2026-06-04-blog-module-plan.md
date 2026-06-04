# Blog / News Module Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in blog/news module to marimo-book built on Material's `blog` plugin + `mkdocs-rss-plugin`, where posts (`.md` or marimo `.py`) drop into `blog/posts/` and flow through the existing render pipeline.

**Architecture:** Blog domain logic lives in one focused module `src/marimo_book/blog.py` (header parsing, default resolution, author-roster merge, teaser insertion, post discovery). The preprocessor calls into it to render+stage posts; `shell.py` wires the `blog`/`tags`/`rss` plugins and nav entry into the generated `mkdocs.yml`; `cli.py` adds a `new-post` scaffold. Every artifact handed to the plugin (`.authors.yml`, post front-matter, RSS config) is standard Material shape for clean zensical portability.

**Tech Stack:** Python 3.11+, pydantic v2, Typer, Material for MkDocs `blog`+`tags` plugins, `mkdocs-rss-plugin`, pytest, ruff.

**Spec:** `notes/2026-06-04-blog-module-design.md`

**Working branch:** `feature/blog-module` (already created).

---

## File structure

| File | Responsibility |
|---|---|
| `src/marimo_book/config.py` | **Modify** — add `Blog` model + `Book.blog` field. |
| `src/marimo_book/blog.py` | **Create** — blog domain logic: `PostMeta`, `parse_blog_block`, `parse_post_header`, `resolve_meta`, `build_author_roster`, `insert_teaser`, `discover_posts`. |
| `src/marimo_book/preprocessor.py` | **Modify** — render+stage posts, write `blog/index.md` + merged `.authors.yml`, gated on `book.blog.enabled`. |
| `src/marimo_book/shell.py` | **Modify** — append `blog`/`tags`/`rss` plugins + nav entry in `emit_mkdocs_yml`. |
| `src/marimo_book/cli.py` | **Modify** — add `new-post` command. |
| `pyproject.toml` | **Modify** — `mkdocs-material>=9.7.0`; add `[blog]` extra (`mkdocs-rss-plugin`). |
| `.github/workflows/ci.yml`, `docs.yml` | **Modify** — install `[blog]` extra. |
| `CLAUDE.md` | **Modify** — feature-flag row + authoring notes. |
| `tests/test_config.py` | **Modify** — `Blog` round-trip. |
| `tests/test_blog.py` | **Create** — unit tests for `blog.py`. |
| `tests/test_preprocessor.py` | **Modify** — end-to-end blog staging. |
| `tests/test_cli_commands.py` | **Modify** — `new-post` scaffold. |

Run tests with `.venv/bin/pytest`; lint with `.venv/bin/ruff` (no global install).

---

## Task 1: `Blog` config model

**Files:**
- Modify: `src/marimo_book/config.py` (add `Blog` near other leaf models ~line 88; add `Book.blog` field ~line 409)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
def test_blog_defaults_off() -> None:
    from marimo_book.config import Book
    book = Book.model_validate({"title": "T", "toc": []})
    assert book.blog.enabled is False
    assert book.blog.title == "Blog"
    assert book.blog.dir == "blog"
    assert book.blog.rss is True
    assert book.blog.default_author is None


def test_blog_round_trip() -> None:
    from marimo_book.config import Book
    payload = {
        "title": "T",
        "toc": [],
        "blog": {"enabled": True, "title": "News", "default_author": "luke"},
    }
    book = Book.model_validate(payload)
    assert book.blog.enabled is True
    assert book.blog.title == "News"
    assert book.blog.default_author == "luke"
    # unknown key rejected
    import pytest
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        Book.model_validate({"title": "T", "toc": [], "blog": {"nope": 1}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_config.py::test_blog_defaults_off -v`
Expected: FAIL — `book.blog` does not exist (AttributeError).

- [ ] **Step 3: Add the `Blog` model and `Book.blog` field**

In `config.py`, after the `Bibliography` model (~line 88):

```python
class Blog(BaseModel):
    """Opt-in blog / news module.

    Posts live by convention in ``<book_root>/<dir>/posts/`` (``.md`` or
    marimo ``.py``) and are rendered through the normal page pipeline, then
    handed to Material's ``blog`` plugin. Off by default.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    title: str = "Blog"            # nav label
    dir: str = "blog"              # source folder under the book root
    rss: bool = True               # emit an RSS feed when enabled
    default_author: str | None = None  # roster id used when a post omits authors
```

In the `Book` model, alongside the other feature flags (after `pdf_export`, ~line 400):

```python
    # Opt-in blog / news module. See the :class:`Blog` docstring. Posts in
    # ``<book_root>/<blog.dir>/posts/`` (.md or .py) are auto-discovered.
    # RSS requires: ``pip install marimo-book[blog]``.
    blog: Blog = Field(default_factory=Blog)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_config.py -k blog -v`
Expected: PASS (all three).

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/config.py tests/test_config.py
git commit -m "feat(blog): add Blog config model + Book.blog field"
```

---

## Task 2: `# /// blog` block parser

The `.py` metadata block mirrors the PEP 723 `# /// script` block in `transforms/pep723.py`. Values are a small TOML subset: `key = "string"`, `key = ["a", "b"]`, `key = true`, bare dates.

**Files:**
- Create: `src/marimo_book/blog.py`
- Test: `tests/test_blog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blog.py
from marimo_book.blog import parse_blog_block


def test_parse_blog_block_reads_fields() -> None:
    src = (
        "# /// blog\n"
        '# title = "marimo-book 0.2 released"\n'
        "# date = 2026-06-04\n"
        '# authors = ["luke", "jane"]\n'
        '# tags = ["release"]\n'
        "# draft = true\n"
        "# ///\n"
        "import marimo\n"
    )
    meta = parse_blog_block(src)
    assert meta == {
        "title": "marimo-book 0.2 released",
        "date": "2026-06-04",
        "authors": ["luke", "jane"],
        "tags": ["release"],
        "draft": True,
    }


def test_parse_blog_block_absent_returns_none() -> None:
    assert parse_blog_block("import marimo\n") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_blog.py::test_parse_blog_block_reads_fields -v`
Expected: FAIL — `No module named 'marimo_book.blog'`.

- [ ] **Step 3: Create `blog.py` with the parser**

```python
# src/marimo_book/blog.py
"""Blog / news module domain logic.

Pure-ish helpers used by the preprocessor (rendering/staging), shell
(plugin wiring), and CLI (scaffold). Everything here produces standard
Material `blog`-plugin inputs so it ports to zensical cleanly.
"""

from __future__ import annotations

import ast
import re

_BLOG_BLOCK_RE = re.compile(
    r"^# /// blog[ \t]*\n(?P<body>(?:^#(?:[ \t].*)?\n)*?)^# ///[ \t]*\n",
    re.MULTILINE,
)


def parse_blog_block(source: str) -> dict | None:
    """Parse a leading ``# /// blog`` metadata block from a .py post.

    Returns a dict of the declared keys, or ``None`` if no block is present.
    Recognised value forms: ``"string"``, ``["a", "b"]``, ``true``/``false``,
    and bare ``YYYY-MM-DD`` dates (returned as the raw string).
    """
    m = _BLOG_BLOCK_RE.search(source)
    if m is None:
        return None
    out: dict = {}
    for raw in m.group("body").splitlines():
        line = raw.lstrip("#").strip()
        if not line or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = _coerce(val.strip())
    return out


def _coerce(val: str):
    if val in ("true", "false"):
        return val == "true"
    if val.startswith(("[", '"', "'")):
        try:
            return ast.literal_eval(val)
        except (ValueError, SyntaxError):
            return val.strip("\"'")
    return val  # bare token (e.g. a date) kept as a string
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_blog.py -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/blog.py tests/test_blog.py
git commit -m "feat(blog): parse the # /// blog metadata block for .py posts"
```

---

## Task 3: `PostMeta`, header parsing, and default resolution

Unifies the two header surfaces (`.md` front-matter, `.py` `# /// blog`) into a `PostMeta` and fills defaults: `date` from a `YYYY-MM-DD-…` filename prefix, else file mtime; `title` from the first `# H1`/`mo.md` heading.

**Files:**
- Modify: `src/marimo_book/blog.py`
- Test: `tests/test_blog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blog.py
from datetime import date as _date
from pathlib import Path

from marimo_book.blog import PostMeta, parse_post_header, resolve_meta


def test_md_front_matter_parsed(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-04-hello.md"
    p.write_text("---\ntitle: Hello\nauthors: [luke]\n---\n\n# Body\n")
    meta = parse_post_header(p)
    assert meta.title == "Hello"
    assert meta.authors == ["luke"]
    assert meta.is_notebook is False


def test_date_defaults_from_filename(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-04-hello.md"
    p.write_text("---\ntitle: Hello\n---\n# Body\n")
    meta = resolve_meta(parse_post_header(p), p, default_author="luke")
    assert meta.date == _date(2026, 6, 4)
    assert meta.authors == ["luke"]   # default applied


def test_title_falls_back_to_first_h1(tmp_path: Path) -> None:
    p = tmp_path / "2026-06-04-x.md"
    p.write_text("---\ndate: 2026-06-04\n---\n\n# Real Title\n\nbody\n")
    meta = resolve_meta(parse_post_header(p), p, default_author=None)
    assert meta.title == "Real Title"
    assert meta.authors == []          # no default → empty
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_blog.py::test_md_front_matter_parsed -v`
Expected: FAIL — `cannot import name 'PostMeta'`.

- [ ] **Step 3: Implement `PostMeta`, `parse_post_header`, `resolve_meta`**

Add to `blog.py` (imports `yaml`, `dataclasses`, `datetime`, `pathlib`):

```python
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

_FRONT_MATTER_RE = re.compile(r"^---[ \t]*\n(?P<yaml>.*?)\n---[ \t]*\n", re.DOTALL)
_FILENAME_DATE_RE = re.compile(r"^(\d{4})-(\d{2})-(\d{2})-")
_H1_RE = re.compile(r"^#[ \t]+(.+?)[ \t]*$", re.MULTILINE)


@dataclass
class PostMeta:
    title: str | None = None
    date: date | None = None
    authors: list[str] = field(default_factory=list)
    categories: list[str] = field(default_factory=list)
    tags: list[str] = field(default_factory=list)
    draft: bool = False
    pin: bool = False
    is_notebook: bool = False
    body: str = ""           # markdown body for .md (after front-matter); "" for .py


def parse_post_header(path: Path) -> PostMeta:
    """Parse a post's header from either .md front-matter or a .py # /// blog block."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        raw = parse_blog_block(text) or {}
        return _meta_from_dict(raw, is_notebook=True, body="")
    m = _FRONT_MATTER_RE.match(text)
    raw = yaml.safe_load(m.group("yaml")) if m else {}
    body = text[m.end():] if m else text
    return _meta_from_dict(raw or {}, is_notebook=False, body=body)


def _meta_from_dict(raw: dict, *, is_notebook: bool, body: str) -> PostMeta:
    def _list(v):
        if v is None:
            return []
        return list(v) if isinstance(v, (list, tuple)) else [v]

    d = raw.get("date")
    parsed_date = None
    if isinstance(d, date):
        parsed_date = d
    elif isinstance(d, str) and d:
        parsed_date = datetime.strptime(d[:10], "%Y-%m-%d").date()

    return PostMeta(
        title=raw.get("title"),
        date=parsed_date,
        authors=_list(raw.get("authors")),
        categories=_list(raw.get("categories")),
        tags=_list(raw.get("tags")),
        draft=bool(raw.get("draft", False)),
        pin=bool(raw.get("pin", False)),
        is_notebook=is_notebook,
        body=body,
    )


def resolve_meta(meta: PostMeta, path: Path, *, default_author: str | None) -> PostMeta:
    """Fill required defaults: date (filename→mtime), title (first H1), default author."""
    if meta.date is None:
        fm = _FILENAME_DATE_RE.match(path.name)
        if fm:
            meta.date = date(int(fm.group(1)), int(fm.group(2)), int(fm.group(3)))
        else:
            meta.date = datetime.fromtimestamp(path.stat().st_mtime).date()
    if not meta.title:
        h1 = _H1_RE.search(meta.body) if not meta.is_notebook else None
        meta.title = h1.group(1) if h1 else path.stem
    if not meta.authors and default_author:
        meta.authors = [default_author]
    return meta
```

> Note on `.py` titles: the rendered markdown isn't available at header-parse time, so `.py` posts fall back to the filename stem unless `title` is set in the `# /// blog` block. Title-from-first-cell is handled in Task 6 after render (it overrides only when `title` came from the stem fallback).

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_blog.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/blog.py tests/test_blog.py
git commit -m "feat(blog): unified PostMeta header parsing + default resolution"
```

---

## Task 4: Author roster merge

Merge `book.yml` authors (auto-derived, slugified ids) with an optional `.authors.yml`; the explicit file wins on id collisions. Produces a dict ready to dump as the staged `.authors.yml`.

**Files:**
- Modify: `src/marimo_book/blog.py`
- Test: `tests/test_blog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blog.py
from marimo_book.blog import author_id, build_author_roster
from marimo_book.config import Author


def test_author_id_slugifies() -> None:
    assert author_id("Luke Chang") == "luke-chang"
    assert author_id("Jane Q. Doe") == "jane-q-doe"


def test_roster_from_book_authors_only() -> None:
    roster = build_author_roster([Author(name="Luke Chang")], authors_yml=None)
    assert "luke-chang" in roster
    assert roster["luke-chang"]["name"] == "Luke Chang"


def test_authors_yml_overrides_on_collision() -> None:
    book_authors = [Author(name="Luke Chang", affiliation="Dartmouth")]
    yml = {"authors": {"luke-chang": {"name": "Luke C.", "description": "Maintainer"}}}
    roster = build_author_roster(book_authors, authors_yml=yml)
    assert roster["luke-chang"]["name"] == "Luke C."         # explicit file wins
    assert roster["luke-chang"]["description"] == "Maintainer"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_blog.py::test_author_id_slugifies -v`
Expected: FAIL — `cannot import name 'author_id'`.

- [ ] **Step 3: Implement `author_id` and `build_author_roster`**

Add to `blog.py` (imports `from .config import Author`):

```python
from .config import Author

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def author_id(name: str) -> str:
    return _SLUG_RE.sub("-", name.lower()).strip("-")


def _derive_entry(a: Author) -> dict:
    desc = a.affiliation or (f"ORCID {a.orcid}" if a.orcid else None)
    entry = {"name": a.name}
    if desc:
        entry["description"] = desc
    return entry


def build_author_roster(book_authors: list[Author], authors_yml: dict | None) -> dict:
    """Merge book.yml-derived authors with an optional .authors.yml roster.

    Returns ``{id: {name, description?, avatar?, url?}}``. The explicit
    .authors.yml entries win on id collision.
    """
    roster = {author_id(a.name): _derive_entry(a) for a in book_authors}
    if authors_yml:
        for id_, entry in (authors_yml.get("authors") or {}).items():
            roster[id_] = entry
    return roster
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_blog.py -k author -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/blog.py tests/test_blog.py
git commit -m "feat(blog): merge book.yml authors with optional .authors.yml roster"
```

---

## Task 5: Teaser insertion

Guarantee an excerpt boundary (`<!-- more -->`) for the index teaser. Respect an author-placed marker; else insert after the first markdown block.

**Files:**
- Modify: `src/marimo_book/blog.py`
- Test: `tests/test_blog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blog.py
from marimo_book.blog import insert_teaser

MORE = "<!-- more -->"


def test_explicit_marker_preserved() -> None:
    md = "Intro.\n<!-- more -->\nRest.\n"
    assert insert_teaser(md) == md


def test_inserts_after_first_paragraph() -> None:
    md = "First para.\n\nSecond para.\n\nThird.\n"
    out = insert_teaser(md)
    assert out.count(MORE) == 1
    assert out.index(MORE) < out.index("Second para.")


def test_inserts_after_leading_heading_block() -> None:
    md = "# Title\n\nFirst para.\n\nSecond.\n"
    out = insert_teaser(md)
    # marker goes after the first paragraph, keeping the H1 in the teaser
    assert out.index(MORE) < out.index("Second.")
    assert out.index("# Title") < out.index(MORE)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_blog.py::test_explicit_marker_preserved -v`
Expected: FAIL — `cannot import name 'insert_teaser'`.

- [ ] **Step 3: Implement `insert_teaser`**

Add to `blog.py`:

```python
_MORE = "<!-- more -->"


def insert_teaser(markdown: str) -> str:
    """Ensure a single ``<!-- more -->`` excerpt boundary.

    If the author already placed one, return unchanged. Otherwise insert it
    after the first non-heading paragraph (so a leading ``# H1`` stays in the
    teaser). If no blank-line-separated block is found, append at the end.
    """
    if _MORE in markdown:
        return markdown
    blocks = markdown.split("\n\n")
    # find the first block that is not purely a heading
    for i, block in enumerate(blocks):
        if block.strip() and not block.lstrip().startswith("#"):
            insert_at = i + 1
            break
    else:
        return markdown.rstrip("\n") + f"\n\n{_MORE}\n"
    blocks.insert(insert_at, _MORE)
    return "\n\n".join(blocks)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_blog.py -k teaser -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/blog.py tests/test_blog.py
git commit -m "feat(blog): auto-insert overridable excerpt teaser boundary"
```

---

## Task 6: Post discovery + front-matter emission helper

`discover_posts` lists post files; `render_front_matter` builds the YAML block the staged `.md` must lead with (used by the preprocessor in Task 7).

**Files:**
- Modify: `src/marimo_book/blog.py`
- Test: `tests/test_blog.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_blog.py
from marimo_book.blog import discover_posts, render_front_matter


def test_discover_posts_finds_md_and_py(tmp_path: Path) -> None:
    posts = tmp_path / "blog" / "posts"
    posts.mkdir(parents=True)
    (posts / "2026-06-04-a.md").write_text("---\ndate: 2026-06-04\n---\nx\n")
    (posts / "2026-06-03-b.py").write_text("# /// blog\n# date = 2026-06-03\n# ///\nimport marimo\n")
    (posts / "ignore.txt").write_text("nope")
    found = sorted(p.name for p in discover_posts(tmp_path / "blog"))
    assert found == ["2026-06-03-b.py", "2026-06-04-a.md"]


def test_render_front_matter_round_trips() -> None:
    meta = PostMeta(title="Hi", date=_date(2026, 6, 4), authors=["luke"], tags=["release"])
    fm = render_front_matter(meta)
    assert fm.startswith("---\n") and fm.rstrip().endswith("---")
    loaded = yaml.safe_load(fm.strip("-\n"))
    assert loaded["title"] == "Hi"
    assert loaded["date"] == _date(2026, 6, 4)
    assert loaded["authors"] == ["luke"]
```

(`import yaml` and `from datetime import date as _date` already present in the test module from earlier tasks.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_blog.py::test_discover_posts_finds_md_and_py -v`
Expected: FAIL — `cannot import name 'discover_posts'`.

- [ ] **Step 3: Implement `discover_posts` and `render_front_matter`**

Add to `blog.py`:

```python
def discover_posts(blog_dir: Path) -> list[Path]:
    """Return all .md/.py post files under ``<blog_dir>/posts/`` (sorted)."""
    posts_dir = blog_dir / "posts"
    if not posts_dir.is_dir():
        return []
    return sorted(
        p for p in posts_dir.iterdir()
        if p.is_file() and p.suffix in (".md", ".py")
    )


def render_front_matter(meta: PostMeta) -> str:
    """Render the YAML front-matter block the staged post .md must lead with."""
    data: dict = {"date": meta.date}
    if meta.title:
        data["title"] = meta.title
    for key in ("authors", "categories", "tags"):
        val = getattr(meta, key)
        if val:
            data[key] = val
    if meta.draft:
        data["draft"] = True
    if meta.pin:
        data["pin"] = True
    dumped = yaml.safe_dump(data, sort_keys=False, allow_unicode=True).strip()
    return f"---\n{dumped}\n---\n"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_blog.py -v`
Expected: PASS (all).

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/blog.py tests/test_blog.py
git commit -m "feat(blog): post discovery + front-matter rendering"
```

---

## Task 7: Preprocessor — render & stage posts

Wire blog rendering into `Preprocessor.build()`. For each discovered post: parse+resolve the header, render its body (`.md` passthrough; `.py` through the existing notebook→markdown render path used by `stage_page`), apply the teaser, prepend front-matter, and write to `_site_src/docs/<dir>/posts/<name>.md`. Then write `<dir>/index.md` and the merged `.authors.yml`.

**Files:**
- Modify: `src/marimo_book/preprocessor.py` (add `_stage_blog`; call it from `build()` after page staging)
- Modify: `src/marimo_book/blog.py` (add `read_authors_yml`)
- Test: `tests/test_preprocessor.py`

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/test_preprocessor.py
def test_blog_stages_posts_index_and_authors(tmp_path: Path) -> None:
    from marimo_book.config import Book
    from marimo_book.preprocessor import Preprocessor

    posts = tmp_path / "blog" / "posts"
    posts.mkdir(parents=True)
    (posts / "2026-06-04-hello.md").write_text(
        "---\ntitle: Hello\n---\n\nIntro para.\n\nMore body.\n", encoding="utf-8"
    )
    book = Book.model_validate({
        "title": "T",
        "toc": [{"file": "content/intro.md"}],
        "authors": [{"name": "Luke Chang"}],
        "blog": {"enabled": True},
    })
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "intro.md").write_text("# Intro\n")

    out = tmp_path / "_site_src"
    report = Preprocessor(book, book_dir=tmp_path).build(out_dir=out)
    assert not report.errors

    docs = out / "docs"
    post = (docs / "blog" / "posts" / "2026-06-04-hello.md").read_text()
    assert post.startswith("---\n")          # front-matter present
    assert "date: 2026-06-04" in post
    assert "authors:\n- luke-chang" in post  # default author applied
    assert "<!-- more -->" in post           # teaser inserted
    assert (docs / "blog" / "index.md").exists()
    authors = (docs / "blog" / ".authors.yml").read_text()
    assert "luke-chang" in authors and "Luke Chang" in authors


def test_blog_disabled_stages_nothing(tmp_path: Path) -> None:
    from marimo_book.config import Book
    from marimo_book.preprocessor import Preprocessor
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "intro.md").write_text("# Intro\n")
    book = Book.model_validate({"title": "T", "toc": [{"file": "content/intro.md"}]})
    out = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out)
    assert not (out / "docs" / "blog").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_preprocessor.py::test_blog_stages_posts_index_and_authors -v`
Expected: FAIL — no `blog/` tree staged.

- [ ] **Step 3a: Add `read_authors_yml` to `blog.py`**

```python
def read_authors_yml(book_dir: Path) -> dict | None:
    """Load ``<book_dir>/.authors.yml`` if present."""
    p = book_dir / ".authors.yml"
    if not p.is_file():
        return None
    return yaml.safe_load(p.read_text(encoding="utf-8"))
```

- [ ] **Step 3b: Add `_stage_blog` to the preprocessor and call it from `build()`**

In `preprocessor.py`, import the blog helpers near the other transform imports:

```python
from .blog import (
    build_author_roster,
    discover_posts,
    insert_teaser,
    parse_post_header,
    read_authors_yml,
    render_front_matter,
    resolve_meta,
)
import yaml
```

Add a method on `Preprocessor` (mirror the style of `_stage_assets`):

```python
    def _stage_blog(self, docs_dir: Path, report: BuildReport) -> None:
        """Render and stage blog posts + index + merged .authors.yml."""
        if not self.book.blog.enabled:
            return
        blog_src = self.book_dir / self.book.blog.dir
        posts = discover_posts(blog_src)
        out_blog = docs_dir / self.book.blog.dir
        out_posts = out_blog / "posts"
        out_posts.mkdir(parents=True, exist_ok=True)

        default_author = self.book.blog.default_author
        if default_author is None and len(self.book.authors) == 1:
            default_author = _author_id(self.book.authors[0].name)

        for src in posts:
            meta = resolve_meta(
                parse_post_header(src), src, default_author=default_author
            )
            if src.suffix == ".py":
                body = self._render_notebook_body(src)   # existing render path
                if meta.title == src.stem:
                    h1 = _first_markdown_heading(body)
                    if h1:
                        meta.title = h1
            else:
                body = meta.body
            body = insert_teaser(body)
            staged = out_posts / (src.stem + ".md")
            staged.write_text(render_front_matter(meta) + "\n" + body, encoding="utf-8")

        # required landing page (content auto-injected by the plugin)
        index = out_blog / "index.md"
        if not index.exists():
            index.write_text(f"# {self.book.blog.title}\n", encoding="utf-8")

        # merged .authors.yml
        roster = build_author_roster(self.book.authors, read_authors_yml(self.book_dir))
        if roster:
            (out_blog / ".authors.yml").write_text(
                yaml.safe_dump({"authors": roster}, sort_keys=False, allow_unicode=True),
                encoding="utf-8",
            )
```

Use `author_id` (imported) for `_author_id`, and add a tiny module-level `_first_markdown_heading` helper in `preprocessor.py`:

```python
def _first_markdown_heading(markdown: str) -> str | None:
    import re
    m = re.search(r"^#[ \t]+(.+?)[ \t]*$", markdown, re.MULTILINE)
    return m.group(1) if m else None
```

For `_render_notebook_body(src)`: extract the existing per-notebook render used by `stage_page` into a small reusable method (return the rendered markdown string for a `.py` file using the same export/precompute path stage_page already uses). If `stage_page` is monolithic, add `Preprocessor._render_notebook_body(self, src: Path) -> str` that performs the same `export_notebook` + `cells_to_markdown` (and wasm/precompute handling) sequence stage_page runs for a single `.py` entry, returning the markdown rather than writing a page. **Reuse, do not duplicate** the transform calls.

Then call it from `build()` right after the page/asset staging block (find where `_stage_assets` / changelog staging is invoked and add):

```python
        self._stage_blog(docs_dir, report)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_preprocessor.py -k blog -v`
Expected: PASS (both). Then full suite: `.venv/bin/pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/preprocessor.py src/marimo_book/blog.py tests/test_preprocessor.py
git commit -m "feat(blog): render and stage posts, index, and merged .authors.yml"
```

---

## Task 8: Shell — wire blog/tags/rss plugins + nav

**Files:**
- Modify: `src/marimo_book/shell.py` (`emit_mkdocs_yml`, plugins block ~line 109-152; nav assembly)
- Test: `tests/test_preprocessor.py` (or a `tests/test_shell.py` if one exists — check; else add to test_preprocessor)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_preprocessor.py
def test_mkdocs_yml_wires_blog_plugins_and_nav(tmp_path: Path) -> None:
    import yaml as _yaml
    from marimo_book.config import Book
    from marimo_book.preprocessor import Preprocessor
    (tmp_path / "content").mkdir()
    (tmp_path / "content" / "intro.md").write_text("# Intro\n")
    (tmp_path / "blog" / "posts").mkdir(parents=True)
    book = Book.model_validate({
        "title": "T", "toc": [{"file": "content/intro.md"}],
        "blog": {"enabled": True, "title": "News", "rss": True},
    })
    out = tmp_path / "_site_src"
    Preprocessor(book, book_dir=tmp_path).build(out_dir=out)
    cfg = _yaml.safe_load((out / "mkdocs.yml").read_text())
    names = [p if isinstance(p, str) else next(iter(p)) for p in cfg["plugins"]]
    assert "blog" in names and "tags" in names and "rss" in names
    assert names.index("blog") < names.index("rss")        # rss after blog
    assert {"News": "blog/index.md"} in cfg["nav"] or any(
        isinstance(n, dict) and n.get("News") == "blog/index.md" for n in cfg["nav"]
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_preprocessor.py::test_mkdocs_yml_wires_blog_plugins_and_nav -v`
Expected: FAIL — no `blog` plugin / nav entry.

- [ ] **Step 3: Add the plugin + nav wiring**

In `shell.py`, in the plugins block (after the `pdf_export` branch, before `cfg["plugins"] = plugins` at ~line 152):

```python
    if book.blog.enabled:
        # Material's blog + tags plugins (free since 9.7.0). rss (optional
        # extra) must follow blog so it can read the generated posts.
        plugins.append({"blog": {"blog_dir": book.blog.dir, "post_excerpt": "optional"}})
        plugins.append("tags")
        if book.blog.rss:
            plugins.append(
                {"rss": {"use_material_blog": True, "match_path": f"{book.blog.dir}/posts/.*"}}
            )
```

Then locate where `cfg["nav"]` is assigned (from `_nav_from_toc`) and append the blog entry when enabled:

```python
    if book.blog.enabled:
        cfg["nav"].append({book.blog.title: f"{book.blog.dir}/index.md"})
```

(Place this after `cfg["nav"]` is set. If nav is built in `_nav_from_toc`, append in `emit_mkdocs_yml` right after the call.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_preprocessor.py -k "blog or mkdocs" -v`
Expected: PASS. Then `.venv/bin/pytest -q`.

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/shell.py tests/test_preprocessor.py
git commit -m "feat(blog): wire blog/tags/rss plugins + nav into generated mkdocs.yml"
```

---

## Task 9: CLI `new-post` scaffold

**Files:**
- Modify: `src/marimo_book/cli.py` (add `@app.command("new-post")`)
- Test: `tests/test_cli_commands.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli_commands.py
def test_new_post_writes_md_stub(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from marimo_book.cli import app
    runner = CliRunner()
    result = runner.invoke(
        app, ["new-post", "Hello World", "--book-dir", str(tmp_path), "--date", "2026-06-04"]
    )
    assert result.exit_code == 0, result.output
    post = tmp_path / "blog" / "posts" / "2026-06-04-hello-world.md"
    assert post.exists()
    text = post.read_text()
    assert text.startswith("---\n")
    assert "date: 2026-06-04" in text
    assert "title: Hello World" in text


def test_new_post_notebook_stub(tmp_path: Path) -> None:
    from typer.testing import CliRunner
    from marimo_book.cli import app
    runner = CliRunner()
    result = runner.invoke(
        app, ["new-post", "Demo", "--notebook", "--book-dir", str(tmp_path), "--date", "2026-06-04"]
    )
    assert result.exit_code == 0, result.output
    post = tmp_path / "blog" / "posts" / "2026-06-04-demo.py"
    assert post.exists()
    assert "# /// blog" in post.read_text()
    assert "import marimo" in post.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/pytest tests/test_cli_commands.py::test_new_post_writes_md_stub -v`
Expected: FAIL — no `new-post` command.

- [ ] **Step 3: Implement the command**

In `cli.py`, add (uses `author_id` from `blog.py`, `date.today` only via a passed `--date` to stay deterministic; default date uses `datetime.now`):

```python
@app.command("new-post")
def new_post(
    title: str = typer.Argument(..., help="Post title"),
    notebook: bool = typer.Option(False, "--notebook", help="Create a marimo .py post"),
    book_dir: Path = typer.Option(Path("."), "--book-dir", help="Book root"),
    date: str | None = typer.Option(None, "--date", help="YYYY-MM-DD (default: today)"),
    author: str | None = typer.Option(None, "--author", help="Author id"),
) -> None:
    """Scaffold a new blog post in <book_dir>/blog/posts/."""
    from datetime import datetime
    from marimo_book.blog import author_id

    day = date or datetime.now().strftime("%Y-%m-%d")
    slug = author_id(title)  # reuse the same slugifier
    posts = book_dir / "blog" / "posts"
    posts.mkdir(parents=True, exist_ok=True)
    ext = ".py" if notebook else ".md"
    dest = posts / f"{day}-{slug}{ext}"
    if dest.exists():
        typer.secho(f"Refusing to overwrite {dest}", fg=typer.colors.RED)
        raise typer.Exit(1)

    authors_line = f'authors = ["{author}"]' if author else "# authors = []"
    if notebook:
        dest.write_text(
            "# /// blog\n"
            f'# title = "{title}"\n'
            f"# date = {day}\n"
            f"# {authors_line}\n"
            "# ///\n"
            "import marimo\n\n"
            'app = marimo.App()\n\n'
            "@app.cell\n"
            "def _():\n"
            "    import marimo as mo\n"
            f'    mo.md("""# {title}\n\n    Write your intro here.""")\n'
            "    return (mo,)\n\n"
            'if __name__ == "__main__":\n'
            "    app.run()\n",
            encoding="utf-8",
        )
    else:
        ya = f"authors: [{author}]\n" if author else ""
        dest.write_text(
            f"---\ntitle: {title}\ndate: {day}\n{ya}---\n\n"
            "Write your intro here.\n\n<!-- more -->\n\nFull post body.\n",
            encoding="utf-8",
        )
    typer.secho(f"Created {dest}", fg=typer.colors.GREEN)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/pytest tests/test_cli_commands.py -k new_post -v`
Expected: PASS (both).

- [ ] **Step 5: Commit**

```bash
git add src/marimo_book/cli.py tests/test_cli_commands.py
git commit -m "feat(blog): add `marimo-book new-post` scaffold command"
```

---

## Task 10: Dependencies + CI/docs workflows

**Files:**
- Modify: `pyproject.toml`
- Modify: `.github/workflows/ci.yml`, `.github/workflows/docs.yml`

- [ ] **Step 1: Bump mkdocs-material and add the `[blog]` extra**

In `pyproject.toml`, change `mkdocs-material>=9.5` → `mkdocs-material>=9.7.0` (free blog plugin + author profiles). In `[project.optional-dependencies]` add:

```toml
blog = [
    "mkdocs-rss-plugin>=1.17",
]
```

- [ ] **Step 2: Install `[blog]` in CI + docs**

In `.github/workflows/ci.yml` and `.github/workflows/docs.yml`, add `blog` to the extras installed in the `pip install -e '.[...]'` line (the docs job needs every extra the docs site uses; add only if the self-hosted docs enable the blog — Task 11).

- [ ] **Step 3: Verify install resolves**

Run: `VIRTUAL_ENV=.venv uv pip install -e '.[dev,blog]'`
Expected: resolves; `mkdocs-rss-plugin` installed.

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml .github/workflows/ci.yml .github/workflows/docs.yml
git commit -m "build(blog): mkdocs-material>=9.7.0 + [blog] extra (mkdocs-rss-plugin)"
```

---

## Task 11: Docs — CLAUDE.md + self-hosted blog example

**Files:**
- Modify: `CLAUDE.md` (feature-flag table)
- Modify: `docs/book.yml` (enable blog) + create `docs/blog/posts/2026-06-04-hello-blog.md` (dogfood + proves the docs build)

- [ ] **Step 1: Add the CLAUDE.md feature-flag row**

Add a row to the feature-flag table:

> `blog.enabled: true` | Adds Material's `blog` + `tags` plugins (and `rss` when `blog.rss`). Posts (`.md` or marimo `.py`) live in `<book>/blog/posts/`; header via front-matter or a `# /// blog` block; bylines from a merged `book.yml` authors + optional `.authors.yml` roster; `marimo-book new-post "Title"` scaffolds one. | `marimo-book[blog]` (RSS only) |

- [ ] **Step 2: Enable the blog on the self-hosted docs + add one post**

In `docs/book.yml` add `blog: {enabled: true, title: News}`. Create `docs/blog/posts/2026-06-04-hello-blog.md`:

```markdown
---
title: marimo-book now has a blog
date: 2026-06-04
---

marimo-book ships an opt-in blog module.

<!-- more -->

Drop a `.md` or marimo `.py` file in `blog/posts/` and it appears here.
```

- [ ] **Step 3: Build the docs strictly**

Run: `.venv/bin/marimo-book build -b docs/book.yml --strict`
Expected: builds; `_site/news/` (or `_site/blog/`) exists with the post. (System cairo for `social` may warn locally — unrelated.)

- [ ] **Step 4: Run the full suite + lint**

Run: `.venv/bin/ruff check src/ tests/ && .venv/bin/ruff format --check src/ tests/ && .venv/bin/pytest -q`
Expected: clean; all pass.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/book.yml docs/blog/posts/2026-06-04-hello-blog.md
git commit -m "docs(blog): CLAUDE.md flag row + dogfood blog on the self-hosted docs"
```

---

## Task 12: CHANGELOG + open PR

- [ ] **Step 1: Add a CHANGELOG `[Unreleased]` entry**

Under `## [Unreleased]` → `### Added`:

```markdown
- **Blog / news module (`blog: {enabled: true}`).** Opt-in blog built on
  Material's blog plugin. Posts (`.md` or marimo `.py`) drop into
  `blog/posts/`; metadata via front-matter or a `# /// blog` block; bylines
  from a merged `book.yml` + `.authors.yml` roster; RSS via
  `marimo-book[blog]`; `marimo-book new-post` scaffolds a post.
```

- [ ] **Step 2: Commit + push + open PR**

```bash
git add CHANGELOG.md
git commit -m "docs(blog): CHANGELOG entry"
git push -u origin feature/blog-module
gh pr create --base main --title "Blog / news module" --body "Implements the design in notes/2026-06-04-blog-module-design.md: opt-in blog on Material's blog plugin. Posts (.md or marimo .py) in blog/posts/; header via front-matter or a # /// blog block; merged book.yml + .authors.yml roster; auto teaser; new-post scaffold; RSS via the new [blog] extra. Off by default; dogfooded on the self-hosted docs."
```

---

## Self-review notes

- **Spec coverage:** content model (T6,T7) · header parsing md+py (T2,T3) · defaults (T3) · author merge/support-both (T4,T7) · teaser (T5) · config (T1) · preprocessor staging (T7) · shell wiring (T8) · RSS (T8,T10) · new-post (T9) · deps (T10) · CLAUDE.md (T11) · tests (every task). Covered.
- **Known reuse point to honor:** Task 7's `_render_notebook_body` MUST reuse the existing `stage_page` render path (export/precompute/wasm), not re-implement it — extract a shared method.
- **Type consistency:** `author_id` (T4) reused in T7 + T9; `PostMeta` fields stable across T3/T5/T6/T7; `Blog` fields (`enabled/title/dir/rss/default_author`) stable across T1/T7/T8.
