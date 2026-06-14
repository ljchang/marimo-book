# GitHub Releases

For books that document a downloadable app (a desktop binary, a CLI, an
installer), `marimo-book` turns a repo's [GitHub
Releases](https://docs.github.com/rest/releases) into two things:

- a **download button** that shows OS-aware "get the latest version" cards, and
- an auto-generated **changelog page**.

Both keep the regular `build` **hermetic** (no network at build time).

## Download button

Drop a placeholder on a page; at view time the browser fetches the repo's
latest release, matches assets to platforms, and renders download cards. The
cards always reflect the current latest release without rebuilding the site —
the same client-hydration pattern marimo-book uses for anywidgets.

## Use it

In a marimo `.py` page:

```python
import marimo as mo
from marimo_book import release_download

release_download("owner/repo", app_name="My App")
```

Or as raw HTML in any Markdown page (or an `mo.Html(...)` cell):

```html
<div data-mb-release-download data-repo="owner/repo" data-app-name="My App"></div>
```

`data-repo` accepts `owner/name` or a full `github.com` URL.

## Platforms

By default the component looks for these assets (case-insensitive substring
match against asset filenames), and renders a card only for the platforms a
given release actually ships:

| Platform | Matches filenames containing |
| --- | --- |
| macOS (Apple Silicon) | `aarch64.dmg` |
| macOS (Intel) | `x64.dmg` |
| Windows | `.msi` |
| Linux (AppImage) | `.appimage` |

A macOS-only release therefore shows a single card. Override the matchers for
custom asset naming:

```python
release_download(
    "owner/repo",
    app_name="My App",
    platforms=[
        {"key": "mac-arm", "label": "macOS (Apple Silicon)", "match": "aarch64.dmg"},
        {"key": "windows", "label": "Windows (x64)", "match": "x64-setup.exe"},
    ],
)
```

`key` drives the "Recommended for you" highlight: the visitor's detected OS
(`mac-arm`, `mac-intel`, `windows`, `linux`) is matched against it.

## Behaviour & resilience

- **Always-fresh, never blocks the build.** The fetch is client-side; the build
  makes no network calls.
- **Rate-limit friendly.** Responses are cached in `sessionStorage` for an hour
  and revalidated with an `ETag` / `If-None-Match` (304), so a reader clicking
  around won't burn through the unauthenticated GitHub API limit (60/hr/IP).
- **Graceful fallback.** On any error — offline, rate-limited, or a **private
  repo** the visitor can't read — the component renders a plain link to the
  repo's releases page instead. A `<noscript>` link is always embedded too, so
  it degrades to a working link with JavaScript disabled and stays crawlable.
- **Safe by construction.** Cards are built with DOM APIs (no `innerHTML`) and
  hrefs are scheme-guarded to `http(s)`, so a release tag or asset name can
  never inject markup.

## Changelog page

`marimo-book sync-releases` generates a Markdown changelog from a repo's
releases. Configure it in `book.yml` and add the output file to your `toc`:

```yaml
# book.yml
release_notes:
  repo: cosanlab/pyfeat-live   # owner/name or URL; defaults to the book's `repo`
  output: changelog.md         # written here (relative to the book root)
  title: "Py-feat Live — Changelog"
  limit: 50                    # optional: cap the number of releases
  include_prereleases: true    # drafts are always excluded

toc:
  - file: changelog.md         # add the generated page once
  # …
```

Then run the generator (it writes/overwrites `changelog.md`):

```bash
marimo-book sync-releases
```

Each release becomes a section with its title, publish date, a link to the
release, and its body (GitHub-flavoured Markdown, embedded verbatim; a leading
`#` in a body is demoted so it doesn't fight the page).

This is a **generate-then-build** step — like `sync-deps`, it makes the only
network call, so `build` stays hermetic and reproducible. The recommended flow:

- **Commit** the generated `changelog.md`.
- Regenerate it in CI when a new release publishes. Have the app repo's release
  workflow fire a [`repository_dispatch`](https://docs.github.com/actions/using-workflows/events-that-trigger-workflows#repository_dispatch)
  at the docs repo; the docs workflow runs `marimo-book sync-releases` (+ commit)
  and rebuilds.
- Set `GITHUB_TOKEN` in the environment for **private** repos or to lift the
  unauthenticated API rate limit.

`marimo-book sync-releases --check` writes nothing and exits non-zero when the
page is stale — a useful CI gate.
