# Workbench: editing notebooks in the browser

A notebook page normally has one view: the rendered page. The *workbench*
adds up to two more — **Run** and **Edit** — that open the same notebook in
marimo's own editor, inside the page, with no server behind it. A reader's
edits are kept in their browser as a local copy of the published notebook,
with a version history, and survive reloads and republishes.

The [WASM demo](wasm_demo.md) page of this book offers all three views;
try **Edit** in its header.

## Enable it

```yaml
toc:
  - file: content/intro_to_pandas.py
    views: [read, run, edit]     # Read | Run | Edit in the header
    open_in: read                # optional; defaults to the first view
```

Any subset works, and `defaults.views` sets a book-wide default:

| `views` | What the reader gets |
|---|---|
| `[read]` (default) | The rendered page. Nothing from the workbench is shipped. |
| `[read, run]` | A **Run** button: the notebook in marimo's present view — every cell live and reactive, code hidden. Nothing is saved (a reader who already has a copy runs that copy). |
| `[read, edit]` | An **Edit** button: the full editor. Edits persist in the reader's browser; **History** and a copy-status chip appear. |
| `[edit]` | The page *is* the editor; no view control is rendered. |

`open_in` chooses the view a page opens in and must be one of that page's
`views` (`marimo-book check` enforces it). The current view rides in the
URL as `?view=edit`, so a reload lands where the reader left off while a
link from the sidebar still opens the page view.

`run` and `edit` need the notebook to boot in Pyodide, like `mode: wasm`
pages: pure-Python dependencies install from the same PEP 723 block the
build stages (see [Dependencies](dependencies.md)), and `check` warns when
a workbench notebook imports something with no Pyodide wheel.

## What the reader sees

The header gains, left of the launch buttons: a status chip (`published`,
or `● your copy · 2 min ago`), the **Read | Run | Edit** control, and
**History**. Switching to Run or Edit replaces the page body with the
editor, which boots marimo's Pyodide kernel — a few seconds on a laptop
the first time, faster once the assets are cached. Read is instant and
always shows the published page.

**Edits are saved automatically** about a second after each change, into
the browser's IndexedDB (per browser and per profile; private windows and
"clear site data" erase it). The first edit creates the reader's copy; from
then on Edit opens that copy, and the header's download button serves it
instead of the published file.

**History** opens a drawer with every version of the copy: the first
opening, automatic checkpoints (every `checkpoint_minutes` of editing, the
last `max_checkpoints` kept), versions the reader names with *Save a
version*, and the snapshots taken around updates and restores. Selecting
one shows a diff against the current copy; *Restore* brings it back (after
snapshotting the current state, so a restore is itself undoable). The
drawer's footer has *Reset to published* and *Delete my copy*, both
two-step.

## When the book is republished

Every build stamps the page with a hash of the published notebook. When a
reader whose copy started from an older version opens Edit, a banner says
*This notebook was updated. Your work is saved.* with three choices:

- **Update and keep my work** replaces the copy with the new version after
  snapshotting the old one — with an *Undo* on the confirmation, and the
  previous copy in History as *Before update*.
- **See what changed** shows the diff between the reader's copy and the
  new version.
- **Not now** keeps the copy; the status chip keeps saying *update
  available* until they decide.

The reader's work is never overwritten silently. (Merging the reader's
edits into the new version cell by cell is a planned refinement; today the
update replaces the notebook and keeps the old copy one click away.)

## What the build ships

Only when some page lists `run` or `edit`:

- `_workbench/assets/` — a copy of marimo's frontend bundle, ~27 MB per
  marimo version. It has to be served from the site itself: the kernel runs
  in web workers, and browsers refuse worker scripts from another origin,
  so a CDN copy would show the editor but never start Python. The copy is
  skipped when the staged one already matches the installed marimo.
- `_workbench/index.html` — the mount page the iframe loads: marimo's own
  page with a small script that installs the IndexedDB file store through
  marimo's public `fileStores` mount option.
- `_workbench/nb/<toc path>.py` — the published notebook, with its PEP 723
  block; its hash is what a reader's copy is compared against.
- `javascripts/workbench.js` and `stylesheets/workbench.css` — the page
  shell (header controls, banner, history drawer), loaded site-wide and
  inert on pages without a workbench.

The editor lives in an iframe on purpose: marimo's stylesheet restyles
`html`, `body` and headings, and the Material page restyles marimo's, so
they need separate documents. Being same-origin, the frame shares the
site's storage and needs no sandbox attributes.

## Diagnostics

Append `?wblog=1` to a page URL before opening Edit and the Pyodide
workers' console output (package installs, kernel errors) is relayed to
the page console as `[worker:…]` lines — useful when a notebook boots but
a dependency does not install.

## Limits

- One workbench per page; the notebook is the page's own `file:`.
- On a `mode: wasm` page the islands runtime still boots underneath a Run
  or Edit view, so two Pyodide kernels run at once. Prefer `views: [read,
  edit]` on `mode: static` pages where the read view doesn't need to be
  reactive.
- Phones get the Read view only; the control hides Run and Edit below
  ~720 px.
- Zensical's ```` ```pyodide ```` fences are a different, lighter tool for
  editing *snippets* in the reading flow; they have no notebook file, no
  reactivity and no persistence, so they don't replace the workbench.
