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
