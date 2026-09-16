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

  // The source marimo boots. Resolved *before* the mount config is written,
  // because marimo reads the notebook's PEP 723 block out of `config.code` to
  // decide what to install (`PyodideSession.find_packages`). With the empty
  // string this used to pass, that path finds nothing and marimo falls back to
  // its "Missing packages" prompt — which installs bare names, so a reader on
  // a chapter with any non-bundled import had to click Install and hope.
  let resolved = null;
  let reading = null;

  const store = {
    // Memoizes the *promise*, not just the value: marimo's own bundle can call
    // this while our pre-read is still awaiting, and two create paths would
    // both fetch, both write the workspace and both record an "initial"
    // version.
    readFile() {
      if (resolved !== null) return Promise.resolve(resolved);
      return (reading ||= this._read().finally(() => (reading = null)));
    },
    async _read() {
      let ws = await WB.getWorkspace(nb);
      if (!ws) {
        const res = await fetch(src, { cache: "no-store" });
        if (!res.ok) throw new Error(`workbench: cannot load ${src} (${res.status})`);
        const published = await res.text();
        if (!persist) {
          post("loaded", { updateAvailable: false, ms: ms() });
          resolved = published; // run view: nothing is written
          return resolved;
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
      resolved = ws.workingSource; // never null → marimo's own fallbacks are never consulted
      return resolved;
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
      // Only after the write landed: a rejected put (quota, with 20 rolling
      // checkpoints of full sources) would otherwise leave the cache claiming
      // a save the store never took, and the History diff would disagree.
      resolved = contents;
      post("saved", { updatedAt: now });
    },
  };

  const boot = window.__WB__ || {};
  const config = boot.config || {};
  config.display = Object.assign({}, config.display, { theme });

  function mountConfig(code) {
    return {
    // The name marimo's save flow requires (without one, Save is a no-op).
    // The worker rewrites this file from our store on every boot.
    filename: "notebook.py",
    code,
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
  }

  // Resolve the notebook, publish the config, *then* start marimo's bundle.
  // Ordering is the whole point: marimo's frontend is a module script, which
  // runs after parsing, so it would otherwise start before an awaited read
  // could fill in `code`. `mount_page_html` holds the bundle back for us and
  // leaves its URL on `__WB__.bundle`.
  //
  // Without a held-back bundle we are running against a mount page from an
  // older marimo-book — a browser can serve one of these two files from cache
  // and the other from the network across an upgrade. That page still has
  // marimo's module script inline, and it will run at the end of parsing,
  // before any awaited read could resolve. So publish the config synchronously
  // and accept the old behaviour (marimo prompts for packages) rather than
  // hand marimo an undefined config and break the page outright.
  if (!boot.bundle) {
    window.__MARIMO_MOUNT_CONFIG__ = mountConfig("");
  } else {
    // Bounded, because marimo's boot now waits on this. `fetch` has no timeout
    // and `indexedDB.open` can block indefinitely behind another tab holding a
    // version change, so an unbounded wait would leave the config unset and the
    // bundle never injected: a blank iframe with no marimo UI at all. Before
    // this change marimo booted immediately and surfaced the stall itself, and
    // falling back to an empty `code` keeps that floor — the reader gets the
    // package prompt, which is the old behaviour, rather than nothing.
    const BOOT_DEADLINE_MS = 10000;
    const timeout = new Promise((resolve) =>
      setTimeout(() => {
        post("error", { message: "timed out reading your copy; booting anyway" });
        resolve("");
      }, BOOT_DEADLINE_MS),
    );
    Promise.race([
      store.readFile().catch((e) => {
        post("error", { message: String((e && e.message) || e) });
        return ""; // let marimo boot and show its own failure
      }),
      timeout,
    ])
      .then((code) => {
        window.__MARIMO_MOUNT_CONFIG__ = mountConfig(code);
        const tag = document.createElement("script");
        tag.type = "module";
        tag.crossOrigin = "anonymous";
        tag.src = boot.bundle;
        document.head.appendChild(tag);
      });
  }

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
