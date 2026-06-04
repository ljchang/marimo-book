"""Blog / news module domain logic.

Pure-ish helpers used by the preprocessor (rendering/staging), shell
(plugin wiring), and CLI (scaffold). Everything here produces standard
Material `blog`-plugin inputs so it ports to zensical cleanly.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path

import yaml

from .config import Author

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
    body: str = ""


def parse_post_header(path: Path) -> PostMeta:
    """Parse a post's header from either .md front-matter or a .py # /// blog block."""
    text = path.read_text(encoding="utf-8")
    if path.suffix == ".py":
        raw = parse_blog_block(text) or {}
        return _meta_from_dict(raw, is_notebook=True, body="")
    m = _FRONT_MATTER_RE.match(text)
    raw = yaml.safe_load(m.group("yaml")) if m else {}
    body = text[m.end() :] if m else text
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
    """Fill required defaults: date (filename->mtime), title (first H1), default author."""
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
    for i, block in enumerate(blocks):
        if block.strip() and not block.lstrip().startswith("#"):
            insert_at = i + 1
            break
    else:
        return markdown.rstrip("\n") + f"\n\n{_MORE}\n"
    blocks.insert(insert_at, _MORE)
    return "\n\n".join(blocks)


def discover_posts(blog_dir: Path) -> list[Path]:
    """Return all .md/.py post files under ``<blog_dir>/posts/`` (sorted)."""
    posts_dir = blog_dir / "posts"
    if not posts_dir.is_dir():
        return []
    return sorted(p for p in posts_dir.iterdir() if p.is_file() and p.suffix in (".md", ".py"))


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
