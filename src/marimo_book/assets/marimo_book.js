// marimo-book runtime shim.
//
// At page load, finds every .marimo-book-anywidget mount emitted by the
// preprocessor, extracts the widget's ES module (inlined by marimo as a
// data: URL), and calls module.default.render({model, el}) with a minimal
// anywidget-compatible model object.
//
// No marimo runtime required. No network fetches. Safe to run on every page
// of a Material for MkDocs (or zensical) site.

(function () {
  "use strict";

  /** Build a minimal anywidget-compatible model from an initial-value dict. */
  function makeModel(initial) {
    const state = Object.assign({}, initial || {});
    const listeners = {};
    return {
      get(key) {
        return state[key];
      },
      set(key, value) {
        const old = state[key];
        state[key] = value;
        const subs = listeners["change:" + key] || [];
        for (const cb of subs) {
          try { cb(value, old); } catch (e) { console.error(e); }
        }
        const any = listeners["change"] || [];
        for (const cb of any) {
          try { cb(key, value, old); } catch (e) { console.error(e); }
        }
      },
      on(eventName, cb) {
        (listeners[eventName] = listeners[eventName] || []).push(cb);
      },
      off(eventName, cb) {
        const subs = listeners[eventName] || [];
        const i = subs.indexOf(cb);
        if (i !== -1) subs.splice(i, 1);
      },
      save_changes() {
        // No kernel to sync to; widgets should tolerate a no-op here.
      },
      send(content, _callbacks, _buffers) {
        console.debug("[marimo-book] model.send ignored (static site)", content);
      },
    };
  }

  /** Safely decode a marimo data-* attribute.
   *
   *  Attribute values are encoded as JSON-stringified strings (so the raw
   *  attribute looks like: data-js-url='"data:text/javascript;base64,..."').
   *  First unescape HTML entities, then try JSON.parse; fall back to the raw
   *  value so malformed attributes don't crash the page.
   */
  function decodeAttr(raw) {
    if (raw == null) return null;
    const doc = new DOMParser().parseFromString(raw, "text/html");
    const unescaped = doc.documentElement.textContent || raw;
    try {
      return JSON.parse(unescaped);
    } catch (_) {
      return unescaped;
    }
  }

  /** Parse an initial-value dict, handling model_id-only blobs gracefully. */
  function parseInitial(raw) {
    const value = decodeAttr(raw);
    if (!value || typeof value !== "object") return {};
    // Marimo emits {"model_id": "..."} when no literal kwargs are inlined;
    // that's a reference to the runtime's model registry and meaningless
    // here. Start from an empty state and let the widget's JS fall back to
    // its own defaults.
    if (Object.keys(value).length === 1 && "model_id" in value) return {};
    return value;
  }

  async function hydrateMount(el) {
    const jsUrl = decodeAttr(el.getAttribute("data-js-url"));
    if (!jsUrl || typeof jsUrl !== "string") {
      console.warn("[marimo-book] mount has no data-js-url", el);
      return;
    }
    let mod;
    try {
      mod = await import(/* @vite-ignore */ jsUrl);
    } catch (err) {
      console.error("[marimo-book] failed to import widget module", err, el);
      el.textContent = "Failed to load widget.";
      return;
    }
    const widget = mod && (mod.default || mod);
    if (!widget || typeof widget.render !== "function") {
      console.warn("[marimo-book] widget module has no .render", el, mod);
      return;
    }
    // Clear placeholder text / stray children before rendering.
    el.innerHTML = "";
    const initial = parseInitial(el.getAttribute("data-initial-value"));
    const model = makeModel(initial);
    try {
      const cleanup = widget.render({ model, el });
      if (typeof cleanup === "function") {
        el.__marimoBookCleanup = cleanup;
      }
    } catch (err) {
      console.error("[marimo-book] widget render threw", err, el);
    }
  }

  function hydrateAll(root) {
    const scope = root || document;
    const mounts = scope.querySelectorAll(".marimo-book-anywidget:not([data-mb-hydrated])");
    mounts.forEach((el) => {
      el.setAttribute("data-mb-hydrated", "1");
      hydrateMount(el);
    });
  }

  // ---- Static reactivity (precompute) ------------------------------------
  //
  // The preprocessor injects three things per page when book.precompute
  // succeeds for that page:
  //
  //   1. <div class="marimo-book-precompute-control">  — empty mount where
  //      we render the input control (range / select / checkbox).
  //   2. <div class="marimo-book-precompute-cell" data-precompute-cell="N">
  //      — wraps each cell whose output differs across widget values.
  //   3. Two <template> blocks: -widget (metadata) and -table (per-value
  //      cell HTML deltas). They were originally <script type="application/json">
  //      but Material's `navigation.instant` re-creates every <script>
  //      tag on page swap and chokes on JSON's first colon with
  //      "Unexpected token ':'", silently dropping the script — leaving
  //      the shim with no data to read on instant-nav arrivals (forcing
  //      a hard refresh). <template> is inert and survives the swap.
  //
  // On input we look up the value's delta and swap the affected cells'
  // innerHTML; cells absent from the delta restore to their initial
  // (default-value) HTML, snapshotted at first init.

  // Read the JSON payload from a precompute data container. Accepts both
  // <template> (current emitter, post-Material-instant-nav-fix) and
  // <script type="application/json"> (legacy emitter, in case stale build
  // caches still emit the old shape). Returns null if the element is
  // missing.
  function readPrecomputeJson(el) {
    if (!el) return null;
    const text =
      el.tagName === "TEMPLATE"
        ? (el.content && el.content.textContent) || el.innerHTML || ""
        : el.textContent || "";
    return JSON.parse(text || "{}");
  }
  // Selector helpers: a precompute container can be either a <template>
  // (current) or a <script> (legacy). Each helper appends an attribute
  // filter to both branches so a single querySelector finds whichever one
  // the emitter wrote.
  function precomputeWidgetSel(filter) {
    return `template.marimo-book-precompute-widget${filter}, script.marimo-book-precompute-widget${filter}`;
  }
  function precomputeTableSel(filter) {
    return `template.marimo-book-precompute-table${filter}, script.marimo-book-precompute-table${filter}`;
  }
  function precomputeGroupSel(filter) {
    return `template.marimo-book-precompute-group${filter}, script.marimo-book-precompute-group${filter}`;
  }

  function valueKey(value) {
    return JSON.stringify(value);
  }

  function buildSliderControl(widget) {
    const wrap = document.createElement("div");
    wrap.className = "marimo-book-precompute-input marimo-book-precompute-input--slider";
    const input = document.createElement("input");
    input.type = "range";
    input.min = "0";
    input.max = String(widget.values.length - 1);
    input.step = "1";
    const defaultIdx = Math.max(0, widget.values.indexOf(widget.default));
    input.value = String(defaultIdx);
    const label = document.createElement("output");
    label.className = "marimo-book-precompute-label";
    label.textContent = String(widget.values[defaultIdx]);
    wrap.appendChild(input);
    wrap.appendChild(label);
    function getValue() { return widget.values[parseInt(input.value, 10)]; }
    function syncLabel() { label.textContent = String(getValue()); }
    return { wrap, input, getValue, syncLabel };
  }

  function buildSelectControl(widget) {
    const wrap = document.createElement("div");
    wrap.className = "marimo-book-precompute-input marimo-book-precompute-input--select";
    const select = document.createElement("select");
    widget.values.forEach((v, i) => {
      const opt = document.createElement("option");
      opt.value = String(i);
      opt.textContent = String(v);
      select.appendChild(opt);
    });
    const defaultIdx = Math.max(0, widget.values.indexOf(widget.default));
    select.value = String(defaultIdx);
    wrap.appendChild(select);
    function getValue() { return widget.values[parseInt(select.value, 10)]; }
    function syncLabel() {}
    return { wrap, input: select, getValue, syncLabel };
  }

  function buildCheckboxControl(widget) {
    const wrap = document.createElement("label");
    wrap.className = "marimo-book-precompute-input marimo-book-precompute-input--checkbox";
    const input = document.createElement("input");
    input.type = "checkbox";
    input.checked = widget.default === true;
    wrap.appendChild(input);
    const span = document.createElement("span");
    span.textContent = " " + (widget.var_name || "value");
    wrap.appendChild(span);
    function getValue() { return input.checked; }
    function syncLabel() {}
    return { wrap, input, getValue, syncLabel };
  }

  function buildControl(widget) {
    if (widget.kind === "slider") return buildSliderControl(widget);
    if (widget.kind === "dropdown" || widget.kind === "radio") return buildSelectControl(widget);
    if (widget.kind === "switch") return buildCheckboxControl(widget);
    return null;
  }

  function initPrecomputeForWidget(scope, varName) {
    const sel = `[data-precompute-widget="${CSS.escape(varName)}"]`;
    const widgetEl = scope.querySelector(precomputeWidgetSel(sel));
    const tableEl = scope.querySelector(precomputeTableSel(sel));
    const controlEl = scope.querySelector(".marimo-book-precompute-control" + sel);
    if (!widgetEl || !tableEl || !controlEl) return;
    if (controlEl.getAttribute("data-mb-precompute-init")) return;

    let widget, table;
    try {
      widget = readPrecomputeJson(widgetEl) || {};
      table = readPrecomputeJson(tableEl) || {};
    } catch (err) {
      // bootAll fires twice on Material instant-nav (DOMContentLoaded /
      // immediate-eval AND document$.subscribe), and the first call
      // sometimes catches a transient DOM where the template element is
      // present but its text content hasn't been integrated yet — the
      // JSON parse rejects on a truncated payload. The second call sees
      // the complete content and succeeds. Log at debug level so the
      // recovery is observable in DevTools but doesn't alarm users.
      console.debug("[marimo-book] precompute JSON parse deferred for " + varName + " (will retry on next bootAll)", err);
      return;
    }

    const built = buildControl(widget);
    if (!built) return;

    // Snapshot the initial (default-value) HTML of cells controlled by THIS
    // widget. Cells controlled by other widgets are left alone — that's
    // how independent multi-widget pages avoid stomping on each other.
    const cells = scope.querySelectorAll(
      `[data-precompute-cell]${sel}`
    );
    const baseSnapshot = {};
    cells.forEach((el) => {
      const idx = el.getAttribute("data-precompute-cell");
      baseSnapshot[idx] = el.innerHTML;
    });

    function applyValue() {
      const value = built.getValue();
      const key = valueKey(value);
      const delta = table[key] || {};
      cells.forEach((el) => {
        const idx = el.getAttribute("data-precompute-cell");
        const html = Object.prototype.hasOwnProperty.call(delta, idx)
          ? delta[idx]
          : baseSnapshot[idx];
        if (html !== undefined && el.innerHTML !== html) {
          el.innerHTML = html;
          // Cell HTML swapped in is a build-time static snapshot — any
          // <div class="marimo-book-plotly"> inside is an un-hydrated
          // placeholder. Re-run plotly hydration for this cell so the
          // plots render in the new content. Idempotent via [data-mb-plotly].
          hydratePlotly(el);
        }
      });
      if (typeof built.syncLabel === "function") built.syncLabel();
    }

    built.input.addEventListener("input", applyValue);
    built.input.addEventListener("change", applyValue);
    controlEl.appendChild(built.wrap);
    controlEl.setAttribute("data-mb-precompute-init", "1");
  }

  function initPrecomputeForGroup(scope, groupId) {
    const sel = `[data-precompute-group="${CSS.escape(groupId)}"]`;
    const metaEl = scope.querySelector(precomputeGroupSel(sel));
    const tableEl = scope.querySelector(precomputeTableSel(sel));
    if (!metaEl || !tableEl) return;

    let meta, table;
    try {
      meta = readPrecomputeJson(metaEl) || {};
      table = readPrecomputeJson(tableEl) || {};
    } catch (err) {
      // See initPrecomputeForWidget — bootAll's idempotent retry covers
      // first-pass parse races on instant-nav.
      console.debug("[marimo-book] precompute group JSON parse deferred for " + groupId + " (will retry on next bootAll)", err);
      return;
    }

    // Build a control for each widget in the group; controls all share
    // an applyValue function that reads every widget's current value
    // and constructs the combo key.
    const widgets = meta.widgets || [];
    const builders = [];
    for (const widgetMeta of widgets) {
      const built = buildControl(widgetMeta);
      if (!built) return; // unsupported widget kind in group; bail entire group
      builders.push(built);
    }

    const cells = scope.querySelectorAll(
      `[data-precompute-cell]${sel}`
    );
    const baseSnapshot = {};
    cells.forEach((el) => {
      const idx = el.getAttribute("data-precompute-cell");
      baseSnapshot[idx] = el.innerHTML;
    });

    function applyValue() {
      const values = builders.map((b) => b.getValue());
      const key = JSON.stringify(values);
      const delta = table[key] || {};
      cells.forEach((el) => {
        const idx = el.getAttribute("data-precompute-cell");
        const html = Object.prototype.hasOwnProperty.call(delta, idx)
          ? delta[idx]
          : baseSnapshot[idx];
        if (html !== undefined && el.innerHTML !== html) {
          el.innerHTML = html;
          // See applyValue in initPrecomputeForWidget — same plotly
          // re-hydration concern.
          hydratePlotly(el);
        }
      });
      builders.forEach((b) => {
        if (typeof b.syncLabel === "function") b.syncLabel();
      });
    }

    // Mount each control in its own .marimo-book-precompute-control div
    // (matched by group + widget name), and bind events.
    widgets.forEach((widgetMeta, i) => {
      const built = builders[i];
      const controlEl = scope.querySelector(
        `.marimo-book-precompute-control${sel}[data-precompute-widget="${CSS.escape(widgetMeta.var_name)}"]`
      );
      if (!controlEl || controlEl.getAttribute("data-mb-precompute-init")) return;
      built.input.addEventListener("input", applyValue);
      built.input.addEventListener("change", applyValue);
      controlEl.appendChild(built.wrap);
      controlEl.setAttribute("data-mb-precompute-init", "1");
    });
  }

  function initPrecomputeOnce(scope) {
    // Independent (per-widget) mounts.
    const widgetMounts = scope.querySelectorAll(
      ".marimo-book-precompute-control:not([data-mb-precompute-init])[data-precompute-widget]:not([data-precompute-group])"
    );
    widgetMounts.forEach((el) => {
      initPrecomputeForWidget(scope, el.getAttribute("data-precompute-widget"));
    });

    // Joint-group mounts. Init each group once even though multiple
    // controls share its group ID.
    const seen = new Set();
    const groupMounts = scope.querySelectorAll(
      ".marimo-book-precompute-control:not([data-mb-precompute-init])[data-precompute-group]"
    );
    groupMounts.forEach((el) => {
      const gid = el.getAttribute("data-precompute-group");
      if (seen.has(gid)) return;
      seen.add(gid);
      initPrecomputeForGroup(scope, gid);
    });
  }

  /** Move launch buttons into Material's header bar.
   *
   * The preprocessor renders the row server-side as
   * `<div class="marimo-book-buttons" data-placement="header">…</div>`.
   * In header-mode, that source row is hidden via CSS and we mount a
   * cloned copy as a child of `.md-header__inner` so the buttons sit
   * in the global top bar. The clone gets the modifier class
   * `marimo-book-buttons--header` which switches the styling to
   * icon-only with a tighter footprint.
   *
   * Also wires `data-marimo-book-print` anchors to window.print() —
   * users get a per-page PDF via the browser's "Save as PDF" without
   * any server-side mkdocs-with-pdf config.
   */
  function mountHeaderButtons(scope) {
    const headerInner = scope.querySelector(".md-header__inner");
    // Find the ORIGINAL source row (not a previous clone). The clone
    // copies all attrs, so we filter on parent: the source lives in the
    // page main, the clone lives in headerInner.
    const candidates = scope.querySelectorAll('.marimo-book-buttons[data-placement="header"]');
    let source = null;
    for (const c of candidates) {
      if (!headerInner || !headerInner.contains(c)) {
        source = c;
        break;
      }
    }
    if (!headerInner || !source || source.hasAttribute("data-mb-relocated")) return;
    source.setAttribute("data-mb-relocated", "");
    // Remove any stale clones from a prior page (Material instant-nav
    // re-renders the header on each navigation, but bootAll runs again
    // so we'd double-mount without this).
    headerInner.querySelectorAll(".marimo-book-buttons--header").forEach(
      (el) => el.remove()
    );
    const clone = source.cloneNode(true);
    clone.classList.add("marimo-book-buttons--header");
    clone.removeAttribute("data-mb-relocated");
    // Insert before the search slot if present, else before the repo
    // link, else just append. This keeps the buttons left of Material's
    // chrome (search + repo link) so they don't get pushed off-screen.
    const search = headerInner.querySelector('[data-md-component="search"]');
    const repo = headerInner.querySelector(".md-header__source");
    const anchor = search || repo;
    if (anchor) {
      headerInner.insertBefore(clone, anchor);
    } else {
      headerInner.appendChild(clone);
    }
  }

  // Plotly hydration. Marimo emits `<marimo-plotly data-figure='{json}'>`
  // for each figure; we rewrap it as `<div class="marimo-book-plotly">`
  // server-side. This shim loads Plotly.js once on first encounter, then
  // calls `Plotly.newPlot` per mount. Idempotent via [data-mb-plotly].
  let _plotlyLoading = null;
  function loadPlotly() {
    if (window.Plotly) return Promise.resolve(window.Plotly);
    if (_plotlyLoading) return _plotlyLoading;
    _plotlyLoading = new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = "https://cdn.jsdelivr.net/npm/plotly.js-dist-min@2.35.2/plotly.min.js";
      s.crossOrigin = "anonymous";
      s.onload = () => resolve(window.Plotly);
      s.onerror = () => reject(new Error("Failed to load Plotly.js"));
      document.head.appendChild(s);
    });
    return _plotlyLoading;
  }

  function hydratePlotly(scope) {
    const mounts = scope.querySelectorAll(".marimo-book-plotly:not([data-mb-plotly])");
    if (!mounts.length) return;
    loadPlotly().then((Plotly) => {
      mounts.forEach((mount) => {
        if (mount.hasAttribute("data-mb-plotly")) return;
        mount.setAttribute("data-mb-plotly", "");
        let figure;
        try {
          figure = JSON.parse(mount.getAttribute("data-figure") || "{}");
        } catch (e) {
          console.warn("marimo-book: bad plotly data-figure", e);
          return;
        }
        let config = {};
        try {
          config = JSON.parse(mount.getAttribute("data-config") || "{}");
        } catch (e) {
          // ignore — empty config is fine
        }
        const layout = figure.layout || {};
        const responsive = { responsive: true, displaylogo: false, ...config };
        Plotly.newPlot(mount, figure.data || [], layout, responsive);
      });
    }).catch((e) => console.warn("marimo-book: plotly hydration failed", e));
  }

  function bootAll(root) {
    const scope = root || document;
    hydrateAll(scope);
    initPrecomputeOnce(scope);
    mountHeaderButtons(scope);
    hydratePlotly(scope);
  }

  // Boot chain: belt-and-suspenders so we run on direct page loads AND
  // on Material's instant-navigation swaps. All boot work is idempotent
  // (guarded by `:not([data-mb-precompute-init])` and `:not([data-mb-hydrated])`
  // so multiple calls are safe). This matters because Material's
  // `document$` is a Subject — subscribers added AFTER its initial
  // emission miss the initial document. Our `defer` script can race
  // that emission depending on script-tag ordering, so we always boot
  // once via DOMContentLoaded / immediate, AND ALSO subscribe to
  // document$ for instant-nav.
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", () => bootAll(document));
  } else {
    bootAll(document);
  }
  if (typeof document$ !== "undefined" && document$.subscribe) {
    document$.subscribe(() => bootAll(document));
  }
})();
