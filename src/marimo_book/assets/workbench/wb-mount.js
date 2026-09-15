// marimo-book workbench — the mount page's script.
//
// Runs before marimo's frontend bundle. Reads the notebook identity from the
// query string, installs an IndexedDB-backed file store, and hands marimo a
// mount config *object* (the html-wasm export freezes a JSON string, which
// cannot carry the `fileStores` functions). Only marimo's public mount
// surface is used: `window.__MARIMO_MOUNT_CONFIG__` and its `fileStores`
// option (marimo-team/marimo#5161).
//
// Query parameters (set by workbench.js when it creates the iframe):
//   nb       notebook id (site path + TOC path) — the IndexedDB key
//   src      URL of the published notebook (with its PEP 723 block)
//   hash     sha256 of that file, stamped by the build
//   theme    light | dark
//   view-as  present → marimo's app-like view (read by marimo itself)
//   persist  0 → the `run` view: boot the reader's copy if one exists, else the
//            published notebook, and never create or save anything
//   cp       minutes between automatic checkpoints
//   keep     rolling checkpoints kept
//   wblog    1 → relay the workers' console output to this page (diagnostics)
(function () {
  const q = new URLSearchParams(location.search);
  const nb = q.get("nb");
  const src = q.get("src");
  const hash = q.get("hash") || "";
  const theme = q.get("theme") === "dark" ? "dark" : "light";
  const persist = q.get("persist") !== "0";
  const checkpointMs = Math.max(1, Number(q.get("cp")) || 10) * 60 * 1000;
  const keepCheckpoints = Math.max(1, Number(q.get("keep")) || 20);
  const t0 = performance.now();
  const ms = () => Math.round(performance.now() - t0);

  // Diagnostics (?wblog=1): marimo's Pyodide workers log package installs
  // and errors to *their* consoles, which DevTools shows but automation
  // usually can't. Wrap each worker script in a blob that mirrors console.*
  // to postMessage; import.meta.url inside the real module is unaffected.
  if (q.get("wblog") === "1") {
    const RealWorker = window.Worker;
    window.Worker = function (url, opts) {
      const abs = new URL(url, location.href).href;
      const wrapper =
        "for (const k of ['log','error','warn','info','debug']) { const orig = console[k].bind(console); console[k] = (...a) => { try { self.postMessage({ __wblog: k, args: a.map((x) => { try { return typeof x === 'string' ? x : JSON.stringify(x); } catch (e) { return String(x); } }) }); } catch (e) {} orig(...a); }; }\n" +
        "self.addEventListener('unhandledrejection', (e) => console.error('[unhandledrejection]', String(e.reason)));\n" +
        "import(" + JSON.stringify(abs) + ");";
      const w = new RealWorker(URL.createObjectURL(new Blob([wrapper], { type: "text/javascript" })), opts);
      w.addEventListener("message", (e) => {
        if (e.data && e.data.__wblog) console.log("[worker:" + (opts && opts.name) + "]", ...e.data.args);
      });
      return w;
    };
  }

  const post = (type, data) => {
    if (parent === window) return;
    parent.postMessage({ source: "wb", nb, type, ...(data || {}) }, location.origin);
  };

  // marimo's save worker regenerates the file from the cells alone, so the
  // PEP 723 header (dependencies, and whatever else rides in it) and the
  // `marimo.App(...)` kwargs are lost on the first save. Re-attach them from
  // the published base so a reboot still installs the notebook's packages.
  const HEADER_RE = /^# \/\/\/ script\n[\s\S]*?^# \/\/\/\n/m;
  const APP_RE = /^app = marimo\.App\([^\n]*\)$/m;
  function restoreHeader(contents, base) {
    if (!base) return contents;
    if (!HEADER_RE.test(contents)) {
      const h = base.match(HEADER_RE);
      if (h) contents = h[0] + "\n" + contents.replace(/^\n+/, "");
    }
    const baseApp = base.match(APP_RE);
    if (baseApp && /^app = marimo\.App\(\)$/m.test(contents)) {
      contents = contents.replace(/^app = marimo\.App\(\)$/m, baseApp[0]);
    }
    return contents;
  }

  const store = {
    async readFile() {
      let ws = await WB.getWorkspace(nb);
      if (!ws) {
        const res = await fetch(src, { cache: "no-store" });
        if (!res.ok) throw new Error(`workbench: cannot load ${src} (${res.status})`);
        const published = await res.text();
        if (!persist) {
          post("loaded", { updateAvailable: false, ms: ms() });
          return published; // run view: nothing is written
        }
        const now = Date.now();
        ws = {
          notebookId: nb,
          baseHash: hash,
          baseSource: published,
          workingSource: published,
          createdAt: now,
          updatedAt: now,
          lastCheckpointAt: now,
        };
        await WB.putWorkspace(ws);
        await WB.addSnapshot({ notebookId: nb, ts: now, reason: "initial", hash, source: published });
        post("created");
      }
      post("loaded", { updateAvailable: Boolean(hash) && ws.baseHash !== hash, ms: ms() });
      return ws.workingSource; // never null → marimo's own fallbacks are never consulted
    },
    async saveFile(contents) {
      if (!persist) return; // run view: nothing is written
      const ws = await WB.getWorkspace(nb);
      if (!ws) return;
      contents = restoreHeader(contents, ws.baseSource);
      if (contents === ws.workingSource) return;
      const now = Date.now();
      ws.workingSource = contents;
      ws.updatedAt = now;
      if (now - (ws.lastCheckpointAt || 0) > checkpointMs) {
        await WB.addSnapshot({ notebookId: nb, ts: now, reason: "checkpoint", hash: ws.baseHash, source: contents });
        ws.lastCheckpointAt = now;
        await WB.pruneCheckpoints(nb, keepCheckpoints);
      }
      await WB.putWorkspace(ws);
      post("saved", { updatedAt: now });
    },
  };

  const boot = window.__WB__ || {};
  const config = boot.config || {};
  config.display = Object.assign({}, config.display, { theme });

  window.__MARIMO_MOUNT_CONFIG__ = {
    // The name marimo's save flow requires (without one, Save is a no-op).
    // The worker rewrites this file from our store on every boot.
    filename: "notebook.py",
    code: "",
    version: boot.marimoVersion || "unknown",
    mode: "edit", // `?view-as=present` in the frame URL opens the app-like view
    serverToken: "",
    config,
    configOverrides: {},
    appConfig: {},
    view: { showAppCode: true },
    fileStores: [store],
    session: null,
    notebook: null,
    runtimeConfig: [],
  };

  // A grader widget inside the notebook announces a successful submission as
  // a `marimo-grader:submitted` DOM event (marimo-grader-client >= 0.1.1);
  // relay it so the page shell records the submission as a version.
  window.addEventListener("marimo-grader:submitted", (e) => {
    const d = (e && e.detail) || {};
    post("submitted", { note: d.attempt ? `attempt ${d.attempt}` : "" });
  });

  // Boot instrumentation for the page's status line.
  let sawEditor = false;
  let sawOutput = false;
  const obs = new MutationObserver(() => {
    if (!sawEditor && document.querySelector(".cm-editor")) {
      sawEditor = true;
      post("editor", { ms: ms() });
    }
    if (!sawOutput) {
      const out = document.querySelector("marimo-cell-output, .output-area");
      if (out && out.textContent && out.textContent.trim()) {
        sawOutput = true;
        post("ran", { ms: ms() });
      }
    }
    if (sawEditor && sawOutput) obs.disconnect();
  });
  obs.observe(document.documentElement, { childList: true, subtree: true });
})();
