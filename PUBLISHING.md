# Publishing to PyPI

This doc is for maintainers. `marimo-book` uses PyPI's [Trusted
Publishers](https://docs.pypi.org/trusted-publishers/) feature — no API
token needed once the one-time setup is done.

## How releases work (the short version)

1. Open a tiny PR that dates the `[Unreleased]` section in
   `CHANGELOG.md` to today (one-line change). Merge it.
2. Go to <https://github.com/ljchang/marimo-book/releases>. The
   `release-drafter` bot has been maintaining a draft populated with
   bullets from every merged PR. Edit if needed, set the tag to
   `v0.1.0a3` (or whatever the next version is), and click **Publish
   release**.
3. The `v*` tag fires `publish.yml`. `hatch-vcs` reads the tag, builds
   a wheel versioned `0.1.0a3`, ships it to PyPI via OIDC.

That's it. **No `pyproject.toml` edit, no `__init__.py` edit, no direct
push to main.** The version is the tag.

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

## Pre-release checks

Before tagging:

```bash
# All tests + lint pass
pytest -q
ruff check src/ tests/
ruff format --check src/ tests/

# Wheel builds cleanly with the right version (hatch-vcs reads from
# `git describe`, so a local build on an untagged commit reports a dev
# version like `0.1.0a3.dev2+gSHA` — that's expected; the real wheel
# from CI builds on the tag and gets a clean version)
python -m build --wheel
python -c "
import zipfile, pathlib
wheel = next(pathlib.Path('dist').glob('marimo_book-*.whl'))
with zipfile.ZipFile(wheel) as z: print(len(z.namelist()), 'entries')
"

# Docs book still builds --strict
marimo-book build -b docs/book.yml --strict
```

CI (`.github/workflows/ci.yml`) runs the first four of these on every
PR — if CI is green the release is safe.

## Versioning

`marimo-book` follows [SemVer](https://semver.org) with the caveat that
0.x.y is pre-stability: breaking changes may happen between minor
versions.

- `0.1.0a1`, `0.1.0a2`, … — alpha releases, API may churn
- `0.1.0rc1` — release candidate
- `0.1.0` — first stable 0.1 release; `book.yml` schema frozen within 0.1.x
- `1.0.0` — `book.yml` schema frozen long-term; breaking changes require major bump

The version lives in **exactly one place**: the latest git tag matching
`v*`. `hatch-vcs` reads it at build time and bakes it into the wheel.
`marimo_book.__version__` resolves it via `importlib.metadata.version`.

Untagged dev commits get versions like `0.1.0a3.dev5+gabc1234.d20260425`
(latest tag + commits-since + short sha + date). That's by design — it
makes pre-release wheels distinguishable without needing a manual bump.

## Release-drafter

`.github/workflows/release-drafter.yml` runs on every merged PR and
keeps a draft Release on github.com up to date. It groups entries by
PR label:

| Label | Section |
|---|---|
| `enhancement`, `feature` | Added |
| `change`, `refactor`, `performance` | Changed |
| `bug`, `fix` | Fixed |
| `removal`, `breaking` | Removed |
| `documentation`, `docs` | Documentation |
| `ci`, `build`, `dependencies` | Build & CI |

Tag PRs with at least one label so they categorize correctly. PRs
labelled `skip-changelog` are excluded.

The bot's draft is your starting point for release notes — edit it
freely before publishing.

## Yanking a release

If a release is broken and you need to prevent new installs:

1. Go to <https://pypi.org/project/marimo-book/#history>
2. Find the version, click "Options" → "Yank"
3. Yank doesn't delete — existing `pip install marimo-book==0.1.0a1` still
   works; it just prevents `pip install marimo-book` from picking that
   version as latest.

Never delete a release; always yank. Deleting the release file means
old users can't pin to it, which breaks reproducibility.
