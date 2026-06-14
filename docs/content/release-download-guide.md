# Release-download button

`marimo-book` ships a **download-the-latest-release** component for books that
document a downloadable app (a desktop binary, a CLI, an installer). Drop a
placeholder on a page; at view time the browser fetches the repo's latest
[GitHub release](https://docs.github.com/rest/releases/releases#get-the-latest-release),
matches assets to platforms, and renders OS-aware download cards.

Nothing happens at build time — the build stays **hermetic and offline-safe**,
and the cards always reflect the current latest release without rebuilding the
site. It's the same client-hydration pattern marimo-book uses for anywidgets.

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
