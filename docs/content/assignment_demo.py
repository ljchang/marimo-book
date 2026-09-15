import marimo

__generated_with = "0.24.2"
app = marimo.App(width="medium")


@app.cell(hide_code=True)
def _():
    import marimo as mo

    return (mo,)


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    # Assignment demo

    This page carries a graded assignment. Press **Assignment** in the header,
    or **Open assignment** on the card at the end of the page, and it opens in
    a drawer along the bottom of the window — a separate notebook, running in
    your browser, that you can work on while this page stays readable above it.
    **Minimize** tucks the drawer down to its bar without stopping the
    notebook; drag the handle to resize it.

    The assignment here is a stand-in with two questions and their checks. In a
    course it would be the student notebook a grading server published, and the
    drawer's bar would also carry sign-in and submission.

    Note what this page does *not* have: a **Read · Run · Edit** control. Its
    `book.yml` entry leaves `views` alone, so the page itself is an ordinary
    static chapter — a chapter your readers cannot run (a GPU notebook, say)
    can still carry an assignment they can.
    """)
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## What the reader gets

    Everything the [workbench](workbench_demo.md) gives a chapter, the
    assignment gets on its own terms:

    - **Its own copy.** Answers save into the browser as you type and are
      still there tomorrow. The chapter's copy and the assignment's are
      separate — an experiment in one can never disturb the other.
    - **Its own history.** **History** in the drawer's bar lists checkpoints,
      versions you name, and every submission, and restores any of them.
    - **Its own updates.** Republish the assignment and the bar says *update
      available*; updating keeps the old copy in History, and Undo is right
      there.

    What a student submits stays byte-for-byte the notebook the grader
    published plus their answers — which is the contract the grader's
    integrity checks rely on, and the reason the assignment is never merged
    into the chapter.

    ## Wiring it up

    ```yaml
    toc:
      - file: content/assignment_demo.py
        assignment: content/assignments/demo_exercises.py
    ```

    The card's title, the grader identity and the list of questions are read
    out of the assignment notebook itself, so there is nothing to keep in sync
    in `book.yml`.

    See [Assignments and grading](assignments-and-grading.md) for the
    publishing flow, and the [Workbench demo](workbench_demo.md) for the
    chapter-level editor.
    """)
    return


if __name__ == "__main__":
    app.run()
