# Assignments and grading

A book can carry graded assignments alongside its chapters. marimo-book does not grade anything itself; it publishes the *student* version of an assignment notebook as an ordinary page and links it to a grading server such as [marimo-grader](https://marimograder.org/), where sign-in, submission, autograding, and feedback live.

## The current flow

1. Write the instructor notebook (solutions, hidden tests, marks) in a private repository and publish it to the grader with `grader publish`. The grader strips the solutions and writes the assignment's identity into the student notebook's PEP 723 block.
2. Commit the generated student notebook into the book, for example under `content/assignments/`, and list it as a plain `file:` entry. `mode: static` with `allow_errors: true` is the sensible choice: unfinished answer cells raise by design, and the page is a preview, not an execution environment.
3. The usual launch buttons do the rest. **Open in molab** opens the committed student notebook, and the grader widget inside it handles sign-in and submit from the student's browser. Chapters that have an assignment can end with a short pointer to its page.

```yaml
toc:
  - section: Assignments
    children:
      - file: content/assignments/how-to-submit.md
      - file: content/assignments/glm.py
        title: "Assignment: GLM"
        mode: static
        allow_errors: true
```

Set `GRADER_RENDER=1` in the environment of `marimo-book build` so the grader's sign-in and submit widgets render as static placeholders on the page instead of live controls that have no kernel behind them.

Republishing an assignment means running `grader publish` again, copying the new student notebook into the book, and rebuilding. The grader keeps every version, so students who opened an older copy can still submit.

## Planned: `sync-assignments`

A `marimo-book sync-assignments` command is planned. It will read the grader's public assignment listing for an offering, write the current student notebooks and a small metadata sidecar (title, due date, points, version) into the book, and let the build add an assignment header and grader-served launch links to those pages, so a republish on the grader becomes a rebuild of the book rather than a copy step. Builds stay hermetic: the command writes committed files and `build` never fetches.

See the [DartBrains](https://dartbrains.org) Assignments section for a live example of the current flow.
