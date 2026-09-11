import marimo

__generated_with = "0.23.16"
app = marimo.App()


@app.cell
def _():
    import marimo as mo

    return (mo,)


@app.cell
def _(mo):
    mo.md("# Anywidget state fixture")
    return


@app.cell
def _():
    import anywidget
    import traitlets

    class BytesWidget(anywidget.AnyWidget):
        """A widget whose render depends on a Bytes trait (like a volume viewer)."""

        _esm = """
        export default {
          render({ model, el }) {
            const view = model.get("payload");
            el.textContent = "bytes:" + (view ? view.byteLength : "none") + " label:" + model.get("label");
          }
        }
        """
        _css = ".bytes-widget { color: teal; }"
        payload = traitlets.Bytes(b"").tag(sync=True)
        empty = traitlets.Bytes(b"").tag(sync=True)
        label = traitlets.Unicode("default").tag(sync=True)
        scale = traitlets.Float(1.0).tag(sync=True)

    return (BytesWidget,)


@app.cell
def _(BytesWidget, mo):
    widget = mo.ui.anywidget(
        BytesWidget(payload=bytes(range(256)) * 4, label="from-kernel", scale=2.5)
    )
    widget
    return


if __name__ == "__main__":
    app.run()
