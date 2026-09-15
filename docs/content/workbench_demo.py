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
    # Workbench demo

    This page is rendered statically — no Python is running as you read it, and
    it loads as fast as any other page in this book. But the header carries
    **Read · Run · Edit**, because its `book.yml` entry says
    `views: [read, run, edit]`.

    Press **Edit**. Marimo's own editor opens in place of this text, with the
    notebook below it; the first time, it spends a few seconds starting Python
    in your browser. Then change something — the cell under this one is a good
    place to start — and watch everything downstream re-run.

    **Your changes are yours to keep.** They save into this browser as you
    type, so you can close the tab and come back to them. **History** in the
    header lists every version of your copy and restores any of them, and if
    this page is ever republished you are *offered* the new version rather than
    losing your work to it.

    **Run** is the middle ground: the notebook live and reactive with the code
    out of the way, and nothing saved.
    """)
    return


@app.cell
def _():
    # ↓ Change these, then watch the table and the summary below update.
    starting_amount = 1000
    annual_rate = 0.05
    years = 10
    return annual_rate, starting_amount, years


@app.cell(hide_code=True)
def _(annual_rate, mo, starting_amount, years):
    balances = []
    balance = starting_amount
    for year in range(1, years + 1):
        balance *= 1 + annual_rate
        balances.append((year, balance))

    rows = "\n".join(f"| {year} | {value:,.2f} |" for year, value in balances)
    mo.md(f"""
    | Year | Balance |
    |---|---|
    {rows}
    """)
    return (balances,)


@app.cell(hide_code=True)
def _(balances, mo, starting_amount):
    final = balances[-1][1]
    mo.md(
        f"After **{len(balances)} years**, {starting_amount:,} becomes "
        f"**{final:,.2f}** — a **{final / starting_amount:.2f}×** return."
    )
    return


@app.cell(hide_code=True)
def _(mo):
    mo.md(r"""
    ## Things worth trying

    - Set `years = 40` and watch the table and the summary follow. Nothing had
      to be re-run by hand: marimo knows which cells depend on `years`.
    - Set `annual_rate` to a string and read the error. Break whatever you
      like — **Reset to published** in History puts the notebook back.
    - Add a cell of your own, reload the page, and confirm it survived.
    - Open **History**, type a note, and press *Save a version*. Change
      something, then restore that version.

    ## A page can offer fewer views

    All three are on here because this page is the feature's demo. A book
    picks the subset it wants: `views: [read, edit]` is the common one — read
    the chapter, or take it over — and a page that lists a single view opens
    straight into it with no control shown at all.

    ## Assignments

    A chapter can also carry a graded assignment, which opens as its own
    notebook in a drawer along the bottom of the window while the chapter
    stays readable above it. That has its own live demo: see the
    [Assignment demo](assignment_demo.md).

    ## How this works

    The editor is marimo's own, served from this site and mounted in a
    same-origin `<iframe>`, so its stylesheet and this page's never meet. Your
    copy lives in the browser's IndexedDB; the build stamps a hash of the
    published notebook on the page, which is how an update is noticed.

    See the [Workbench](workbench.md) guide for the configuration, what the
    build ships, and the limits — and
    [Assignments and grading](assignments-and-grading.md) for the drawer.
    """)
    return


if __name__ == "__main__":
    app.run()
