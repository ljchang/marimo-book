"""Execute a marimo notebook and export it as ipynb plus its anywidget modules.

Standalone script (``python _export_runner.py NB.py --output OUT.ipynb
--models OUT.json``) run by :func:`marimo_book.transforms.marimo_export.export_notebook`
in place of ``python -m marimo export ipynb --include-outputs``.

Why it exists: since marimo 0.24 (marimo-team/marimo#10127) an anywidget's ES
module no longer rides on the ``<marimo-anywidget>`` element as
``data-js-url``. It travels on the kernel's ``ModelOpen`` notification as an
``EsmSpec`` and the session view keeps it per model — but ``marimo export
ipynb`` only serializes cell outputs, so the module is lost and every widget
renders empty. This script mirrors marimo's own ``export_ipynb`` (execute →
``Exporter.export_as_ipynb``) and additionally writes ``{model_id: js_url}``
from the session view's model notifications. ``/@file/`` virtual-file URLs
are read out of marimo's shared-memory store while the session is still
alive and inlined as ``data:`` URLs, so the map is self-contained.

The same session view also holds every model's *state* (synced traits,
binary buffers, ``_css``), which the ipynb likewise never carries. With
``--states OUT.json`` the script writes that too — the sidecar
:func:`marimo_book.transforms.widget_state.load_widget_states` reads so the
static page can start each widget from the values the kernel rendered.

Deliberately imports ONLY marimo (no marimo_book): under ``--sandbox`` it
runs inside marimo's ``uv run --isolated`` environment, where marimo-book is
not installed. Everything used here is marimo-private and covered by the
same pin rationale as ``transforms/pep723.py`` (see pyproject.toml).

Exit status mirrors marimo's export: 0 on success, 1 if any cell raised
(the ipynb is still written, with the error outputs).
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import sys
from pathlib import Path

_VIRTUAL_PREFIXES = ("/@file/", "./@file/")


def _esm_data_url(url: str) -> str | None:
    """Return an importable URL for an ``EsmSpec.url``; ``None`` if unreadable."""
    if url.startswith(("data:", "http://", "https://")):
        return url
    for prefix in _VIRTUAL_PREFIXES:
        if url.startswith(prefix):
            from marimo._runtime.virtual_file import read_virtual_file

            spec = url[len(prefix) :]
            try:
                byte_length, basename = spec.split("-", 1)
                payload = read_virtual_file(basename, int(byte_length))
            except Exception:  # noqa: BLE001 — any failure just means "no module"
                return None
            return "data:text/javascript;base64," + base64.b64encode(payload).decode("ascii")
    return None


def _serialize_states(session_view) -> dict:
    """``session_view.model_states`` → the widget_state.py sidecar payload (v1)."""
    models: dict[str, dict] = {}
    for model_id, ms in getattr(session_view, "model_states", {}).items():
        state = dict(getattr(ms, "state", {}) or {})
        css = state.pop("_css", None)
        state.pop("_esm", None)
        buffers = [
            {"path": list(path), "b64": base64.b64encode(bytes(blob)).decode("ascii")}
            for path, blob in (getattr(ms, "buffers", {}) or {}).items()
        ]
        models[str(model_id)] = {
            "state": state,
            "buffers": buffers,
            "css": css if isinstance(css, str) and css else None,
        }
    return {"version": 1, "models": models}


async def _run(path: Path, sort_mode: str) -> tuple[str, dict[str, str], dict, bool]:
    from marimo._export.exporter import Exporter
    from marimo._export.file import run_notebook
    from marimo._export.requests import (
        IPYNBExportOptions,
        IPYNBExportRequest,
        NotebookExecutionOptions,
        RunNotebookRequest,
    )
    from marimo._messaging.notification import ModelOpen
    from marimo._output.hypertext import patch_html_for_non_interactive_output
    from marimo._session.notebook import load_notebook

    file_manager = load_notebook(str(path))
    with patch_html_for_non_interactive_output():
        session_view, did_error = await run_notebook(
            RunNotebookRequest(
                file_manager=file_manager,
                options=NotebookExecutionOptions(
                    cli_args={}, argv=[], quiet=True, stderr=sys.stderr
                ),
            )
        )

    ipynb = Exporter().export_as_ipynb(
        IPYNBExportRequest(
            app=file_manager.app,
            options=IPYNBExportOptions(sort_mode=sort_mode),  # type: ignore[arg-type]
            session_view=session_view,
        )
    )

    models: dict[str, str] = {}
    for notification in session_view.get_model_notifications():
        message = notification.message
        if isinstance(message, ModelOpen) and message.esm_spec is not None:
            resolved = _esm_data_url(message.esm_spec.url)
            if resolved:
                models[str(notification.model_id)] = resolved
    try:
        states = _serialize_states(session_view)
    except Exception as exc:  # noqa: BLE001 — state is best-effort; never fail the export
        states = {"version": 1, "error": repr(exc)}
    return ipynb, models, states, did_error


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("notebook")
    parser.add_argument("--output", required=True)
    parser.add_argument("--models", required=True)
    parser.add_argument("--states", default=None)
    parser.add_argument("--sort", default="topological", choices=["topological", "top-down"])
    args = parser.parse_args(argv)

    ipynb, models, states, did_error = asyncio.run(_run(Path(args.notebook), args.sort))
    Path(args.output).write_text(ipynb, encoding="utf-8")
    Path(args.models).write_text(json.dumps(models), encoding="utf-8")
    if args.states:
        Path(args.states).write_text(json.dumps(states), encoding="utf-8")
    return 1 if did_error else 0


if __name__ == "__main__":
    sys.exit(main())
