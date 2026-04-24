# Publishing to PyPI

This doc is for maintainers. `marimo-book` uses PyPI's [Trusted
Publishers](https://docs.pypi.org/trusted-publishers/) feature — no API
token needed once the one-time setup is done.

## One-time setup

### 1. PyPI Trusted Publisher

Go to <https://pypi.org/manage/account/publishing/> and register a
**Pending Publisher**:

| Field | Value |
|---|---|
| PyPI project name | `marimo-book` |
| Owner | `ljchang` |
| Repository name | `marimo-book` |
| Workflow name | `publish.yml` |
| Environment name | `pypi-publish` |

(You only need a Pending Publisher the first time — the project name
hasn't been claimed yet. After the first release, it becomes a regular
Trusted Publisher.)

### 2. GitHub environment

Create a `pypi-publish` environment on the repo:

```bash
gh api --method PUT /repos/ljchang/marimo-book/environments/pypi-publish
```

Optionally add protection rules (require manual approval, restrict to
`main`, etc.) at
<https://github.com/ljchang/marimo-book/settings/environments>.

### 3. TestPyPI dry-run (optional but recommended)

For the very first release, verify the packaging on TestPyPI before
committing to the real index:

```bash
# Register a Trusted Publisher on TestPyPI with the same settings as above.
# Then temporarily change publish.yml to use test.pypi.org:
#
#     with:
#       repository-url: https://test.pypi.org/legacy/
#
# Tag something like v0.1.0a1-test and push, then revert.
```

## Release flow

Once setup is done, releases are a single tag:

```bash
# Version bump (edit in pyproject.toml AND src/marimo_book/__init__.py)
# Update CHANGELOG.md

git add pyproject.toml src/marimo_book/__init__.py CHANGELOG.md
git commit -m "Release v0.1.0a1"
git tag v0.1.0a1
git push origin main --tags
```

GitHub Actions picks up the `v*` tag, builds `sdist` + `wheel`, and
publishes to PyPI via OIDC. Watch it run at
<https://github.com/ljchang/marimo-book/actions/workflows/publish.yml>.

## Pre-release checks

Before tagging:

```bash
# All tests + lint pass
pytest -q
ruff check src/ tests/
ruff format --check src/ tests/

# Wheel builds cleanly and includes everything
python -m build --wheel
python -c "
import zipfile, pathlib
wheel = next(pathlib.Path('dist').glob('marimo_book-*.whl'))
with zipfile.ZipFile(wheel) as z: print(len(z.namelist()), 'entries')
"

# Fresh-venv install smoke test
uv venv /tmp/mb-fresh --python 3.13
uv pip install --python /tmp/mb-fresh/bin/python dist/marimo_book-*.whl
/tmp/mb-fresh/bin/marimo-book new /tmp/mb-fresh-book
cd /tmp/mb-fresh-book && /tmp/mb-fresh/bin/marimo-book build

# Docs book still builds --strict
cd -
marimo-book build -b docs/book.yml --strict
```

CI (`.github/workflows/ci.yml`) runs the first four of these on every
PR — if CI is green you can tag with confidence. The fresh-venv smoke
test is worth doing locally for major releases since CI uses editable
installs which can hide packaging bugs.

## Versioning

`marimo-book` follows [SemVer](https://semver.org) with the caveat that
0.x.y is pre-stability: breaking changes may happen between minor
versions.

- `0.1.0a1`, `0.1.0a2`, … — alpha releases, API may churn
- `0.1.0rc1` — release candidate
- `0.1.0` — first stable 0.1 release; `book.yml` schema frozen within 0.1.x
- `1.0.0` — `book.yml` schema frozen long-term; breaking changes require major bump

Version lives in two places that must stay in sync:

- `pyproject.toml` → `[project] version = ...`
- `src/marimo_book/__init__.py` → `__version__ = ...`

A pre-commit hook or release script could enforce this; today it's
manual.

## Yanking a release

If a release is broken and you need to prevent new installs:

1. Go to <https://pypi.org/project/marimo-book/#history>
2. Find the version, click "Options" → "Yank"
3. Yank doesn't delete — existing `pip install marimo-book==0.1.0a1` still
   works; it just prevents `pip install marimo-book` from picking that
   version as latest.

Never delete a release; always yank. Deleting the release file means
old users can't pin to it, which breaks reproducibility.
