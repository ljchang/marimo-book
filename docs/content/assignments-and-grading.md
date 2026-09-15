# Assignments and grading

A book can carry graded assignments alongside its chapters. marimo-book does not grade anything itself; it publishes the *student* version of an assignment notebook and lets students work on it in the page, while a grading server such as [marimo-grader](https://marimograder.org/) owns sign-in, submission, autograding and feedback.

## Attach an assignment to a chapter

Point the chapter's TOC entry at the student notebook the grader published:

```yaml
toc:
  - file: content/intro_to_pandas.py
    views: [read, run, edit]                       # optional; see the Workbench guide
    assignment: content/assignments/pandas.py      # the grader-published student notebook
```

The page then ends with an **assignment card** — title, grader identity and the question headings, all read from the notebook itself — and gains an **Assignment** toggle in the header. *Open assignment* slides a **drawer** up from the bottom of the page with the assignment in its own editor, under a bar of its own: status, a grader sign-in chip, **History**, **Minimize** and **Hide**. The drawer is drag-resizable and can stay open while the student scrolls the chapter above it. [Try it on the WASM demo page.](wasm_demo.md)

The assignment is its own notebook with its own local copy, never merged into the chapter — what a student submits is byte-for-byte what the grader published plus their answers, which is what integrity checks on the grader side rely on. Everything the [workbench](workbench.md) does for a chapter copy applies to the assignment copy too: autosave in the browser, a version history with restore, and — when a new version is published — an *Update…* button in the drawer bar (and *update available* in its status) that replaces the copy after snapshotting it, with Undo; never forced.

What the card and drawer show comes from the notebook's own PEP 723 block, which the grader writes at publish time:

```python
# /// script
# dependencies = ["marimo", "marimo-grader-client"]
# grader-server = "https://grader.example.edu"
# grader-assignment = "pandas"
# grader-version = "3"
# ///
```

`grader-server` enables the sign-in chip (it runs the grader's device sign-in flow and stores the token where the grader widget inside the notebook reads it); the widget cells in the notebook handle checks and submission as they do anywhere else. A notebook without a grader block still opens in the drawer — it is simply an exercise sheet with a local copy, like the sample on the demo page. `marimo-book check` errors on a missing or non-notebook assignment file and warns when the file has no PEP 723 block.

The grader must allow the book's origin (CORS) for sign-in and submit to work from the page; the sign-in chip says so when it can't reach the server.

## The publishing flow

1. Write the instructor notebook (solutions, hidden tests, marks) in a private repository and publish it with `grader publish`. The grader strips the solutions and writes the assignment's identity into the student notebook's PEP 723 block.
2. Commit the generated student notebook into the book, for example under `content/assignments/`, and reference it from the chapter's `assignment:`. It needs no TOC entry of its own.
3. Rebuild. Republishing an assignment means running `grader publish` again, copying the new student notebook in, and rebuilding; students who already have a copy see an update banner in the drawer's history and keep their answers.

Set `GRADER_RENDER=1` in the environment of `marimo-book build` if you also list assignment notebooks as pages of their own, so the grader's widgets render as static placeholders there.

## Planned: `sync-assignments`

A `marimo-book sync-assignments` command is planned. It will read the grader's public assignment listing for an offering and write the current student notebooks and a small metadata sidecar (title, due date, points, version) into the book, so `assignment: pandas` can name the grader's slug and a republish on the grader becomes a rebuild rather than a copy step. Builds stay hermetic: the command writes committed files and `build` never fetches.

See the [DartBrains](https://dartbrains.org) chapters for a live example.
