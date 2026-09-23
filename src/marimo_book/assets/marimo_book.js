// marimo-book runtime shim.
//
// At page load, finds every .marimo-book-anywidget mount emitted by the
// preprocessor, extracts the widget's ES module (inlined by marimo as a
// data: URL), and calls module.default.render({model, el}) with a minimal
// anywidget-compatible model object.
//
// No marimo runtime required. The only network fetches are the widget's own
// binary buffers (``data-buffers``, baked at build time under
// assets/anywidget/). Safe to run on every page of a Material for MkDocs (or
// zensical) site.

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

  /** Resolve the site root from our own <script src> (mkdocs rewrites it
   *  per page, so this works whatever use_directory_urls / site_url are). */
  let _siteRoot = null;
  function siteRoot() {
    if (_siteRoot !== null) return _siteRoot;
    const script = document.querySelector('script[src*="marimo_book.js"]');
    try {
      _siteRoot = script ? new URL("../", script.src).href : new URL("./", location.href).href;
    } catch (_) {
      _siteRoot = "./";
    }
    return _siteRoot;
  }

  /** Assign `value` into `obj` at a bufferPaths-style path (["a", 0, "b"]). */
  function setAtPath(obj, path, value) {
    if (!Array.isArray(path) || path.length === 0) return;
    let cur = obj;
    for (let i = 0; i < path.length - 1; i++) {
      const key = path[i];
      if (cur[key] === undefined || cur[key] === null || typeof cur[key] !== "object") {
        cur[key] = typeof path[i + 1] === "number" ? [] : {};
      }
      cur = cur[key];
    }
    cur[path[path.length - 1]] = value;
  }

  /** Fetch the build-time buffers listed on `data-buffers` into `state`.
   *
   *  Each entry is {path, url, size} or {path, empty: true}. Buffers are
   *  delivered as DataView, matching what anywidget's own wire format hands
   *  a widget's `model.get(trait)` for a `traitlets.Bytes` trait.
   */
  async function loadBuffers(el, state) {
    const refs = decodeAttr(el.getAttribute("data-buffers"));
    if (!Array.isArray(refs) || refs.length === 0) return;
    const root = siteRoot();
    await Promise.all(
      refs.map(async (ref) => {
        if (!ref || !Array.isArray(ref.path)) return;
        if (ref.empty || !ref.url) {
          setAtPath(state, ref.path, new DataView(new ArrayBuffer(0)));
          return;
        }
        const res = await fetch(new URL(ref.url, root).href);
        if (!res.ok) {
          throw new Error(`[marimo-book] buffer ${ref.url}: HTTP ${res.status}`);
        }
        setAtPath(state, ref.path, new DataView(await res.arrayBuffer()));
      })
    );
  }

  /** Inject a widget's `_css` once per module hash. */
  const _cssInjected = new Set();
  function injectCss(el) {
    const css = el.getAttribute("data-css");
    if (!css) return;
    const key = el.getAttribute("data-js-hash") || css;
    if (_cssInjected.has(key)) return;
    _cssInjected.add(key);
    const style = document.createElement("style");
    style.setAttribute("data-marimo-book-anywidget-css", "");
    style.textContent = css;
    document.head.appendChild(style);
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

  // Marimo's runtime checks `firstElementChild.__type__ === "__custom_marimo_element__"`
  // before calling `firstElementChild.rerender()` (when a parent <marimo-ui-element>
  // changes its random-id, signalling that downstream cell HTML should refresh).
  // We satisfy that contract so:
  //   1. The runtime stops logging
  //      `[marimo-ui-element] first child must have a rerender method`.
  //   2. We get a hook to pull live trait values out of the runtime's
  //      UIElementRegistry and propagate them to the widget's local model
  //      via model.set(trait, value), which fires the widget's existing
  //      change:<trait> listeners and the rAF loop's next frame picks up
  //      the new state — no DOM swap, no re-mount, no kernel round-trip.
  const MARIMO_RERENDER_TYPE = "__custom_marimo_element__";

  // Lazy-loaded global driver registry keyed by parent
  // <marimo-ui-element>.object-id. Populated from the build-time
  // <script type="application/json" class="marimo-book-anywidget-drivers">
  // blob the preprocessor injects at the top of <body>. This is the only
  // location that reliably survives WASM mode's island-content rebuild —
  // marimo's runtime replaces every descendant of <marimo-island> when
  // it first paints kernel output, so attributes on the build-time
  // <marimo-ui-element> and our mount div are both wiped. The fresh
  // ui-element keeps the same object-id, though, so the global lookup
  // by object-id stays correct.
  let _driverRegistry = null;
  function loadDriverRegistry() {
    if (_driverRegistry !== null) return _driverRegistry;
    _driverRegistry = {};
    const blob = document.querySelector(
      "script[type='application/json'].marimo-book-anywidget-drivers"
    );
    if (!blob || !blob.textContent) return _driverRegistry;
    try {
      const parsed = JSON.parse(blob.textContent);
      if (parsed && typeof parsed === "object") _driverRegistry = parsed;
    } catch (_) {}
    return _driverRegistry;
  }

  /** Read `data-driven-by` from `el`, the parent ui-element, or the global registry.
   *
   *  Three layers of fallback:
   *  1. The mount div's own attribute (works for static + precompute pages
   *     where the build-time div is never replaced).
   *  2. The surrounding ui-element's attribute (works in any path where
   *     the ui-element survives but only the inner mount is rewrapped).
   *  3. The global registry, looked up by the ui-element's object-id —
   *     the only resort in WASM mode after the kernel re-renders the
   *     entire island contents (which strips both the mount and the
   *     parent's `data-driven-by` attributes; only object-id is stable).
   */
  function readDrivenBy(el) {
    const own = el.getAttribute && el.getAttribute("data-driven-by");
    if (own) return own;
    const parent = el.closest && el.closest("marimo-ui-element");
    if (parent) {
      const parentOwn = parent.getAttribute("data-driven-by");
      if (parentOwn) return parentOwn;
      const objId = parent.getAttribute("object-id");
      if (objId) {
        const registry = loadDriverRegistry();
        const entry = registry[objId];
        if (entry) return JSON.stringify(entry);
      }
    }
    return null;
  }

  /** Apply a kernel-side slider→trait map to the local model. */
  function applyDrivers(el, model) {
    let drivenBy;
    try {
      drivenBy = JSON.parse(readDrivenBy(el) || "{}");
    } catch (_) {
      return;
    }
    if (!drivenBy || typeof drivenBy !== "object") return;
    const reg = window._marimo_private_UIElementRegistry;
    if (!reg || typeof reg.lookupValue !== "function") return;
    for (const [trait, objectId] of Object.entries(drivenBy)) {
      if (typeof objectId !== "string") continue;
      let value;
      try {
        value = reg.lookupValue(objectId);
      } catch (_) {
        continue;
      }
      // Skip undefined (control not yet hydrated) and {model_id: ...} blobs
      // (anywidgets reference each other this way; not a primitive trait).
      if (value === undefined) continue;
      if (
        value && typeof value === "object" &&
        Object.keys(value).length === 1 && "model_id" in value
      ) continue;
      model.set(trait, value);
    }
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
    // Binary traits (volumes, images, arrays) were written to
    // assets/anywidget/ at build time; pull them in before the widget's
    // render() runs so model.get(trait) already returns the DataView.
    try {
      await loadBuffers(el, initial);
    } catch (err) {
      console.error("[marimo-book] failed to load widget buffers", err, el);
      el.textContent = "Failed to load widget data.";
      return;
    }
    injectCss(el);
    const model = makeModel(initial);
    // Pull initial slider values from the runtime registry (if WASM is up
    // by the time we hydrate), so the first paint matches the user's
    // current control state instead of the build-time defaults.
    applyDrivers(el, model);
    // Mark element so marimo's runtime treats us as a rerenderable host.
    el.__type__ = MARIMO_RERENDER_TYPE;
    el.rerender = function () {
      // Marimo bumps the parent <marimo-ui-element>'s random-id every time
      // a dependent cell finishes re-executing. Re-pull driver values so
      // the widget reflects the new slider position.
      applyDrivers(el, model);
    };
    try {
      const cleanup = widget.render({ model, el });
      if (typeof cleanup === "function") {
        // The mount can be replaced while its module and buffers load; its
        // removal was seen before there was anything to clean up.
        if (el.isConnected) el.__marimoBookCleanup = cleanup;
        else cleanup();
      }
    } catch (err) {
      console.error("[marimo-book] widget render threw", err, el);
    }
  }

  // Mounts this page has rendered into. The data-mb-hydrated attribute alone
  // can't say that: on WASM pages marimo's islands runtime captures an
  // island's DOM after we hydrate it and, when the kernel starts, re-inserts
  // that serialized copy -- attribute included, but with blank canvases and
  // no render loop behind them. Readers saw every widget go empty for the
  // seconds between kernel start and the live widget's first paint.
  const hydratedMounts = new WeakSet();

  function hydrateAll(root) {
    const scope = root || document;
    scope.querySelectorAll(".marimo-book-anywidget").forEach((el) => {
      if (hydratedMounts.has(el)) return;
      hydratedMounts.add(el);
      el.setAttribute("data-mb-hydrated", "1");
      hydrateMount(el);
    });
  }

  // marimo re-inserts those copies without dispatching
  // marimo-island-source-changed, so watch for them directly. Mounts that
  // leave the page for good get their widget's cleanup run, which stops
  // render loops that would otherwise keep drawing into detached canvases.
  // Observers are notified in creation order and this one is created first,
  // so a removed mount may not have been moved into holdBakedFrames' overlay
  // yet when this callback runs; decide on cleanup in a later task, after
  // every observer has seen the batch.
  function watchMountCopies() {
    const SEL = ".marimo-book-anywidget";
    const collect = (nodes, out) => {
      for (const n of nodes) {
        if (!(n instanceof Element)) continue;
        if (n.matches(SEL)) out.push(n);
        else if (n.firstElementChild) out.push(...n.querySelectorAll(SEL));
      }
    };
    new MutationObserver((records) => {
      const added = [];
      const removed = [];
      for (const r of records) {
        collect(r.addedNodes, added);
        collect(r.removedNodes, removed);
      }
      if (removed.length) {
        setTimeout(() => {
          for (const el of removed) {
            if (el.isConnected || !hydratedMounts.has(el)) continue;
            const cleanup = el.__marimoBookCleanup;
            el.__marimoBookCleanup = null;
            if (typeof cleanup === "function") {
              try { cleanup(); } catch (_) {}
            }
          }
        }, 0);
      }
      for (const el of added) {
        if (el.isConnected && !hydratedMounts.has(el)) {
          hydrateAll(el.parentElement || document);
        }
      }
    }).observe(document.documentElement, { childList: true, subtree: true });
  }
  watchMountCopies();

  // ---- WASM mode and runtime-emitted anywidgets -----------------------------
  //
  // Build-time `rewrite_anywidget_html` rewrites every `<marimo-anywidget>`
  // marimo emits into our `<div class="marimo-book-anywidget">` mount, and
  // (marimo >= 0.24) restores its `data-js-url` from the session view, so
  // static, precompute AND the pre-hydration paint of WASM pages all go
  // through `hydrateMount` above.
  //
  // Once Pyodide boots and the islands runtime re-executes the widget cells,
  // marimo's own runtime renders the fresh `<marimo-anywidget>` elements
  // itself: since marimo 0.24 (marimo-team/marimo#10127) the widget's ES
  // module reaches the frontend through the kernel's model notifications and
  // a widget registry, and the old "Refusing to load anywidget module from
  // untrusted URL" failure is gone. Verified in a browser: with no shim at
  // all, the runtime paints the widget into the element's shadow root, and
  // its state round-trips to the kernel natively. An earlier MutationObserver
  // here rewrapped those runtime elements into our static mount — on 0.24
  // that only replaced a working widget with an empty div — so the runtime
  // is left alone. Our build-time mounts are simply replaced when the
  // kernel repaints the island.
  //
  // That replacement is visible: the baked widget vanishes and the island
  // collapses until the live element has fetched its module from the kernel
  // and drawn (250-900 ms per widget on MR_Physics, measured 2026-09-22), so
  // readers see every widget load, disappear, and come back. holdBakedFrames
  // covers the gap without touching the live element: when the baked mount
  // is replaced, the last one is put back as an inert overlay on top and the
  // island keeps its height; both go as soon as the live widget has drawn.
  const HOLD_TIMEOUT_MS = 8000;

  function liveWidgetDrawn(aw) {
    const sr = aw.shadowRoot;
    if (!sr || aw.getBoundingClientRect().height <= 20) return false;
    for (const el of sr.querySelectorAll("*")) {
      if (el.tagName !== "STYLE" && el.tagName !== "LINK" && el.tagName !== "SCRIPT") return true;
    }
    return false;
  }

  function afterPaint(cb) {
    // Two frames so the live widget's first draw is on screen before the
    // overlay lifts; the timer covers background tabs, where frames pause.
    let done = false;
    const go = () => { if (!done) { done = true; cb(); } };
    requestAnimationFrame(() => requestAnimationFrame(go));
    setTimeout(go, 250);
  }

  function holdBakedFrames(root) {
    const scope = root || document;
    const islands = scope.querySelectorAll("marimo-island:not([data-mb-hold])");
    for (const island of islands) {
      if (!island.querySelector(".marimo-book-anywidget")) continue;
      island.setAttribute("data-mb-hold", "");
      let baked = null;
      let height = 0;
      let holding = false;
      const remember = () => {
        // The latest *hydrated* mount: payload materialization can swap in
        // fresh build-time markup that is hydrated again before the kernel runs.
        const m = [...island.querySelectorAll(".marimo-book-anywidget")].find(
          (el) => hydratedMounts.has(el)
        );
        if (m) {
          baked = m;
          height = island.getBoundingClientRect().height;
        }
      };
      remember();
      const observer = new MutationObserver(() => {
        if (holding) return;
        const live = island.querySelector("marimo-anywidget");
        if (!live || !baked || baked.isConnected) {
          remember();
          return;
        }
        holding = true;
        observer.disconnect();
        const prevPosition = island.style.position;
        const prevMinHeight = island.style.minHeight;
        if (getComputedStyle(island).position === "static") island.style.position = "relative";
        if (height > 0) island.style.minHeight = height + "px";
        const overlay = document.createElement("div");
        overlay.className = "marimo-book-held-frame";
        overlay.setAttribute("aria-hidden", "true");
        overlay.appendChild(baked);
        island.appendChild(overlay);
        const started = performance.now();
        const release = () => {
          overlay.remove();
          island.style.position = prevPosition;
          island.style.minHeight = prevMinHeight;
        };
        const check = () => {
          if (!live.isConnected) return release();
          if (liveWidgetDrawn(live)) return afterPaint(release);
          if (performance.now() - started > HOLD_TIMEOUT_MS) return release();
          setTimeout(check, 30);
        };
        check();
      });
      observer.observe(island, { childList: true, subtree: true });
    }
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
    if (widget.label) controlEl.setAttribute("data-label", String(widget.label));

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
          // <div class="marimo-book-plotly"> or <div class="marimo-book-anywidget">
          // inside is an un-hydrated placeholder. Re-run hydration for
          // this cell so the plots / widgets render in the new content.
          // Idempotent via [data-mb-plotly] / [data-mb-hydrated].
          hydratePlotly(el);
          hydrateAll(el);
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
          // See applyValue in initPrecomputeForWidget — same re-hydration
          // concern for both plotly and anywidget mounts.
          hydratePlotly(el);
          hydrateAll(el);
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
      if (widgetMeta.label) controlEl.setAttribute("data-label", String(widgetMeta.label));
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

  /** GitHub's octocat, for the header repository link.
   *
   * A second copy of ``_ICON_GITHUB`` in launch_buttons.py: the launch-button
   * row is rendered server-side in Python, this link is mounted client-side,
   * and there is no build step that could share one constant between them.
   * ``test_header_repo_link.py`` asserts the two paths stay byte-identical,
   * so the duplication cannot drift unnoticed.
   */
  const REPO_ICON =
    '<svg class="marimo-book-button-icon" viewBox="0 0 24 24" ' +
    'aria-hidden="true" focusable="false">' +
    '<path d="M12 .3a12 12 0 0 0-3.79 23.4c.6.11.82-.26.82-.58v-2.05c-3.34.7' +
    "2-4.04-1.61-4.04-1.61-.55-1.39-1.34-1.76-1.34-1.76-1.08-.74.08-.73.08-" +
    ".73 1.2.09 1.83 1.24 1.83 1.24 1.07 1.84 2.81 1.31 3.5 1 .11-.78.42-1." +
    "31.76-1.61-2.67-.3-5.47-1.33-5.47-5.93 0-1.31.46-2.38 1.24-3.22-.13-.3" +
    "1-.54-1.53.11-3.18 0 0 1.01-.32 3.31 1.23a11.5 11.5 0 0 1 6 0c2.31-1.5" +
    "5 3.31-1.23 3.31-1.23.66 1.65.25 2.87.13 3.18.77.84 1.24 1.91 1.24 3.2" +
    "2 0 4.61-2.81 5.62-5.49 5.92.42.36.81 1.1.81 2.22v3.29c0 .32.21.69.83." +
    '58A12 12 0 0 0 12 .3"/></svg>';

  /** Put a link to the book's repository in Material's header.
   *
   * `repo:` in book.yml becomes mkdocs `repo_url`, which Material renders as
   * `.md-header__source`: a card carrying the repo name plus star and fork
   * counts it fetches from the GitHub API. extra.css hides that card, because
   * the counts lag reality and mislead. The side effect was that a book with
   * `repo:` set had no repository link in its header at all unless the page
   * happened to be a notebook with a GitHub launch button -- so on a book of
   * Markdown pages, or one with `launch_buttons.github: false`, there was no
   * way to reach the source from the site.
   *
   * We mount our own icon-only link instead, reading the URL straight out of
   * the hidden element. Nothing new has to be plumbed through mkdocs.yml, and
   * the link appears if and only if `repo:` is set.
   *
   * Suppressed when this page's header already carries a GitHub launch button,
   * which points at the page's own source in the same repository. Two octocats
   * side by side is the duplication hiding Material's card was meant to avoid.
   */
  function mountHeaderRepoLink(scope) {
    const headerInner = scope.querySelector(".md-header__inner");
    if (!headerInner) return;
    // Material re-renders the header on instant-nav and bootAll runs again,
    // so drop the previous page's link before deciding whether to add one.
    headerInner
      .querySelectorAll(".marimo-book-repo-link")
      .forEach((el) => el.remove());
    if (headerInner.querySelector(".marimo-book-button-github")) return;
    const source = headerInner.querySelector(".md-header__source a[href]");
    if (!source) return;
    const wrap = document.createElement("div");
    wrap.className = "marimo-book-repo-link";
    const link = document.createElement("a");
    link.className = "marimo-book-button";
    link.href = source.href;
    link.target = "_blank";
    link.rel = "noopener";
    link.title = "View this project on GitHub";
    link.setAttribute("aria-label", "View this project on GitHub");
    link.innerHTML =
      REPO_ICON + '<span class="marimo-book-button-label">GitHub</span>';
    wrap.appendChild(link);
    // Left of the search slot, the same anchor mountHeaderButtons uses, so
    // this link and a launch-button row land in one group of chrome. Not
    // where Material's own repo card sat (right of search): a reader never
    // sees that card, but they do see two marimo-book sites side by side,
    // and the octocat has to be in the same place on both -- one of them
    // gets it from a launch button and the other from here.
    const anchor =
      headerInner.querySelector('[data-md-component="search"]') ||
      headerInner.querySelector(".md-header__source");
    if (anchor) headerInner.insertBefore(wrap, anchor);
    else headerInner.appendChild(wrap);
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
        // Register animation frames after the initial plot — without this the
        // serialized `figure.frames` are dropped, so play/pause buttons and the
        // slider have nothing to animate (the figure renders only frame 0).
        Plotly.newPlot(mount, figure.data || [], layout, responsive).then(() => {
          if (Array.isArray(figure.frames) && figure.frames.length) {
            Plotly.addFrames(mount, figure.frames);
          }
        });
      });
    }).catch((e) => console.warn("marimo-book: plotly hydration failed", e));
  }

  // Vega / Vega-Lite hydration (Altair charts). marimo formats a chart as
  // an `application/vnd.vegalite.v*+json` spec (or `<marimo-mime-renderer>`
  // inside a container); the preprocessor emits `<div class="marimo-book-vega"
  // data-spec='{json}' data-mime="…">`. This shim loads vega, vega-lite and
  // vega-embed once from jsdelivr, then embeds each mount. Idempotent via
  // [data-mb-vega]; re-embeds on Material's light/dark toggle so axes and
  // labels stay legible.
  const VEGA_SCRIPTS = [
    "https://cdn.jsdelivr.net/npm/vega@6.4.0/build/vega.min.js",
    "https://cdn.jsdelivr.net/npm/vega-lite@6.4.3/build/vega-lite.min.js",
    "https://cdn.jsdelivr.net/npm/vega-embed@7.2.0/build/vega-embed.min.js",
  ];
  let _vegaLoading = null;
  function loadScriptOnce(src) {
    return new Promise((resolve, reject) => {
      const s = document.createElement("script");
      s.src = src;
      s.crossOrigin = "anonymous";
      s.onload = () => resolve();
      s.onerror = () => reject(new Error("Failed to load " + src));
      document.head.appendChild(s);
    });
  }
  function loadVega() {
    if (window.vegaEmbed) return Promise.resolve(window.vegaEmbed);
    if (_vegaLoading) return _vegaLoading;
    // Sequential: vega-lite needs vega, vega-embed needs both.
    _vegaLoading = VEGA_SCRIPTS.reduce(
      (chain, src) => chain.then(() => loadScriptOnce(src)),
      Promise.resolve()
    ).then(() => window.vegaEmbed);
    return _vegaLoading;
  }

  function isDarkScheme() {
    return document.body.getAttribute("data-md-color-scheme") === "slate";
  }

  function embedVega(mount, vegaEmbed) {
    let spec;
    try {
      spec = JSON.parse(mount.getAttribute("data-spec") || "{}");
    } catch (e) {
      console.warn("marimo-book: bad vega data-spec", e);
      return;
    }
    const mime = mount.getAttribute("data-mime") || "";
    const opts = { actions: false };
    if (!spec.$schema) opts.mode = mime.indexOf("vegalite") !== -1 ? "vega-lite" : "vega";
    // marimo stores the user's `alt.renderers.set_embed_options(...)` under
    // usermeta.embedOptions; honour it like marimo's own component does.
    const userOpts = spec.usermeta && spec.usermeta.embedOptions;
    if (userOpts && typeof userOpts === "object") Object.assign(opts, userOpts);
    if (isDarkScheme()) {
      opts.theme = opts.theme || "dark";
      // The dark theme paints a solid dark background; let the page's own
      // background show through instead (`config` wins over `theme`).
      opts.config = Object.assign({ background: "transparent" }, opts.config || {});
    }
    while (mount.firstChild) mount.removeChild(mount.firstChild);
    vegaEmbed(mount, spec, opts).catch((e) => console.warn("marimo-book: vega embed failed", e));
  }

  function hydrateVega(scope) {
    const mounts = scope.querySelectorAll(".marimo-book-vega:not([data-mb-vega])");
    if (!mounts.length) return;
    loadVega().then((vegaEmbed) => {
      mounts.forEach((mount) => {
        if (mount.hasAttribute("data-mb-vega")) return;
        mount.setAttribute("data-mb-vega", "");
        embedVega(mount, vegaEmbed);
      });
    }).catch((e) => console.warn("marimo-book: vega hydration failed", e));
  }

  // Re-embed on palette toggle (Material flips data-md-color-scheme on <body>).
  let _vegaSchemeObserver = null;
  function watchSchemeForVega() {
    if (_vegaSchemeObserver || !document.body || typeof MutationObserver === "undefined") return;
    _vegaSchemeObserver = new MutationObserver(() => {
      if (!window.vegaEmbed) return;
      document.querySelectorAll(".marimo-book-vega[data-mb-vega]").forEach((mount) => {
        embedVega(mount, window.vegaEmbed);
      });
    });
    _vegaSchemeObserver.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });
  }

  // --- marimo theme sync (WASM / islands pages) ----------------------------
  //
  // Nothing themes a marimo island unless the host page does it. `ThemeProvider`
  // — the component that stamps `dark` on <body>, which is what the whole
  // bundle's CSS keys off (`.marimo:is(.dark *)`) — lives in marimo's
  // `mount.tsx` and is used by the full app only; the islands entry point never
  // mounts it. So a `mode: wasm` page stays light no matter what Material's
  // palette says, and stays light when the reader toggles it.
  //
  // Three hooks, three jobs.
  //
  // `class="dark"` on <body> is the one that does the real work: every color
  // token in the islands bundle resolves through it. (marimo's own Radix colour
  // scales are scoped `.marimo .dark`, which can never match a class on <body>
  // — an upstream scoping bug. Those are mid-greys that read on either ground,
  // so the page still lands; nothing we can fix from out here.)
  //
  // `data-theme` is the second check in marimo's islands theme inference, which
  // decides what the *JS-side* consumers (Vega, mermaid, the JSON viewer, data
  // tables) render as. Written on every boot so that theme is decided rather
  // than sniffed off the computed background. (Material's palette applies the
  // stored preference from a blocking <script> at the end of the body, before
  // this deferred one runs, so the scheme has settled by the time we read it.)
  //
  // `data-vscode-theme-kind` is the only theme input marimo recomputes after
  // boot: a MutationObserver on <body> feeds the atom that *overrides* the
  // inferred theme, so writing it re-themes those JS consumers live, which no
  // CSS class could do. marimo also reads the attribute's mere presence as
  // "running inside the VS Code extension" and hides a couple of data-table
  // controls, so it is written only once the scheme actually changes under a
  // booted page: a reader who never toggles keeps the full table UI.
  let _themeObserver = null;
  let _appliedScheme = null;
  function currentScheme() {
    return isDarkScheme() ? "dark" : "light";
  }
  function applyMarimoTheme(scheme, reactive) {
    const body = document.body;
    body.classList.toggle("dark", scheme === "dark");
    body.dataset.theme = scheme;
    if (reactive) {
      body.dataset.vscodeThemeKind =
        scheme === "dark" ? "vscode-dark" : "vscode-light";
    }
  }
  function syncMarimoTheme() {
    if (!document.body) return;
    const scheme = currentScheme();
    if (_appliedScheme === null) _appliedScheme = scheme;
    applyMarimoTheme(scheme, _appliedScheme !== scheme);
    if (_themeObserver || typeof MutationObserver === "undefined") return;
    _themeObserver = new MutationObserver(() => {
      const next = currentScheme();
      // Material rewrites every data-md-color-* attribute on each emission,
      // so only a changed value means the reader (or the OS) switched.
      if (next === _appliedScheme) return;
      _appliedScheme = next;
      applyMarimoTheme(next, true);
    });
    _themeObserver.observe(document.body, {
      attributes: true,
      attributeFilter: ["data-md-color-scheme"],
    });
  }

  // --- Release-download component ------------------------------------------
  //
  // Placeholders `<div data-mb-release-download data-repo data-app-name
  // data-platforms>` are hydrated client-side: fetch the repo's latest
  // GitHub release, match assets to platforms, render OS-aware download
  // cards. Build stays hermetic; data is always current. Falls back to a
  // plain releases link on any error (network, rate-limit, private repo).
  const RD_CACHE_TTL_MS = 60 * 60 * 1000; // 1 hour

  function rdDetectPlatform() {
    if (typeof navigator === "undefined") return "unknown";
    const ua = navigator.userAgent;
    if (/Mac/.test(ua)) return "mac-arm"; // default Apple Silicon
    if (/Win/.test(ua)) return "windows";
    if (/Linux/.test(ua) && !/Android/.test(ua)) return "linux";
    return "unknown";
  }

  function rdFormatSize(bytes) {
    if (!bytes) return "";
    return (bytes / (1024 * 1024)).toFixed(1) + " MB";
  }

  function rdExtension(name) {
    if (/\.AppImage$/i.test(name)) return "APPIMAGE";
    if (/\.tar\.gz$/i.test(name)) return "TAR.GZ";
    const ext = name.split(".").pop() || "";
    return ext.toUpperCase();
  }

  // Raw read, ignoring TTL. The TTL only decides whether to *revalidate*
  // (send If-None-Match) — a 304 means our stored payload is still current,
  // so the 304 path reads it raw rather than re-erroring as "expired".
  function rdReadRaw(repo) {
    try {
      const raw = sessionStorage.getItem("mb-rd-" + repo);
      if (!raw) return null;
      const obj = JSON.parse(raw);
      if (!obj || typeof obj.ts !== "number") return null;
      return obj;
    } catch (_e) {
      return null;
    }
  }

  function rdGetCached(repo) {
    const obj = rdReadRaw(repo);
    if (!obj) return null;
    return Date.now() - obj.ts > RD_CACHE_TTL_MS ? null : obj.data;
  }

  function rdSetCached(repo, data) {
    try {
      sessionStorage.setItem(
        "mb-rd-" + repo,
        JSON.stringify({ data, ts: Date.now() })
      );
    } catch (_e) {
      /* storage full / unavailable — non-fatal */
    }
  }

  // Short-lived negative cache: after a failed fetch (offline, rate-limited,
  // private repo) don't re-hit the API on every instant-nav / reload for a
  // while — just show the fallback. Unauthenticated GitHub allows only
  // 60 req/hr/IP, so a docs site without this could lock itself out.
  const RD_NEG_TTL_MS = 10 * 60 * 1000;

  function rdNegativeCached(repo) {
    try {
      const ts = parseInt(sessionStorage.getItem("mb-rd-neg-" + repo) || "", 10);
      return !isNaN(ts) && Date.now() - ts < RD_NEG_TTL_MS;
    } catch (_e) {
      return false;
    }
  }

  function rdSetNegative(repo) {
    try {
      sessionStorage.setItem("mb-rd-neg-" + repo, String(Date.now()));
    } catch (_e) {
      /* non-fatal */
    }
  }

  function rdMatchAssets(json, platforms) {
    const assets = Array.isArray(json.assets) ? json.assets : [];
    const out = [];
    platforms.forEach((p) => {
      const needle = (p.match || "").toLowerCase();
      const hit = assets.find(
        (a) => a.name && a.name.toLowerCase().includes(needle)
      );
      if (hit) {
        out.push({
          key: p.key || p.label,
          label: p.label,
          url: hit.browser_download_url,
          name: hit.name,
          size: hit.size,
        });
      }
    });
    return { version: json.tag_name, assets: out };
  }

  // Build elements via the DOM (textContent, not innerHTML) so externally-
  // influenced strings (release tag names, asset filenames from the GitHub
  // API) can never inject markup. hrefs are scheme-guarded to http(s).
  function rdEl(tag, cls, text) {
    const node = document.createElement(tag);
    if (cls) node.className = cls;
    if (text != null) node.textContent = text;
    return node;
  }

  function rdSafeHref(url) {
    try {
      const u = new URL(url, window.location.href);
      return u.protocol === "https:" || u.protocol === "http:" ? u.href : "#";
    } catch (_e) {
      return "#";
    }
  }

  function rdClear(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  function rdRenderFallback(el, repo, appName) {
    rdClear(el);
    const a = rdEl(
      "a",
      "marimo-book-release-download__fallback",
      "Download the latest " + (appName || "release") + " on GitHub"
    );
    a.href = rdSafeHref("https://github.com/" + repo + "/releases/latest");
    a.target = "_blank";
    a.rel = "noopener";
    el.appendChild(a);
  }

  function rdRender(el, release, appName) {
    if (!release || !release.assets || release.assets.length === 0) {
      rdRenderFallback(el, el.getAttribute("data-repo"), appName);
      return;
    }
    const detected = rdDetectPlatform();
    const single = release.assets.length === 1;
    // UA can't reliably distinguish Apple Silicon from Intel, so when a
    // release ships BOTH mac builds we can't honestly recommend one — show
    // neither as "recommended" rather than steering Intel users to arm64.
    const macCount = release.assets.filter(
      (a) => a.key === "mac-arm" || a.key === "mac-intel"
    ).length;
    const macAmbiguous = detected === "mac-arm" && macCount > 1;

    rdClear(el);

    const head = rdEl("div", "marimo-book-release-download__head");
    head.appendChild(
      rdEl(
        "span",
        "marimo-book-release-download__version",
        "Latest: " + (release.version || "")
      )
    );
    el.appendChild(head);

    const grid = rdEl(
      "div",
      "marimo-book-release-download__grid" +
        (single ? " marimo-book-release-download__grid--single" : "")
    );
    release.assets.forEach((a) => {
      const recommended = a.key === detected && !single && !macAmbiguous;
      const card = rdEl(
        "a",
        "marimo-book-release-card" +
          (recommended ? " marimo-book-release-card--recommended" : "")
      );
      card.href = rdSafeHref(a.url);
      card.setAttribute(
        "aria-label",
        "Download " + (appName || "") + " for " + a.label
      );
      if (recommended) {
        card.appendChild(
          rdEl("span", "marimo-book-release-card__rec", "Recommended for you")
        );
      }
      card.appendChild(rdEl("span", "marimo-book-release-card__plat", a.label));
      const meta = rdExtension(a.name) + (a.size ? " · " + rdFormatSize(a.size) : "");
      card.appendChild(rdEl("span", "marimo-book-release-card__meta", meta));
      grid.appendChild(card);
    });
    el.appendChild(grid);
  }

  function hydrateReleaseDownloads(scope) {
    const mounts = scope.querySelectorAll(
      "[data-mb-release-download]:not([data-mb-rd-init])"
    );
    mounts.forEach((el) => {
      el.setAttribute("data-mb-rd-init", "");
      const repo = el.getAttribute("data-repo");
      const appName = el.getAttribute("data-app-name") || "";
      if (!repo) {
        return;
      }
      let platforms = [];
      try {
        platforms = JSON.parse(el.getAttribute("data-platforms") || "[]");
      } catch (_e) {
        platforms = [];
      }

      const cached = rdGetCached(repo);
      if (cached) {
        rdRender(el, cached, appName);
        return;
      }
      if (rdNegativeCached(repo)) {
        rdRenderFallback(el, repo, appName);
        return;
      }

      const api = "https://api.github.com/repos/" + repo + "/releases/latest";
      const headers = { Accept: "application/vnd.github+json" };
      let etag = null;
      try {
        etag = sessionStorage.getItem("mb-rd-etag-" + repo);
      } catch (_e) {
        /* no storage */
      }
      if (etag) headers["If-None-Match"] = etag;

      fetch(api, { headers })
        .then((res) => {
          if (res.status === 304) {
            // Our stored payload is still current — read it RAW (ignoring
            // the TTL that triggered this revalidation) and refresh the TTL.
            const raw = rdReadRaw(repo);
            if (raw) {
              rdSetCached(repo, raw.data);
              return raw.data;
            }
            throw new Error("304 without a cached payload");
          }
          if (!res.ok) throw new Error("HTTP " + res.status);
          const tag = res.headers.get("ETag");
          if (tag) {
            try {
              sessionStorage.setItem("mb-rd-etag-" + repo, tag);
            } catch (_e) {
              /* no storage */
            }
          }
          return res.json().then((json) => {
            const data = rdMatchAssets(json, platforms);
            rdSetCached(repo, data);
            return data;
          });
        })
        .then((data) => rdRender(el, data, appName))
        .catch(() => {
          rdSetNegative(repo);
          rdRenderFallback(el, repo, appName);
        });
    });
  }

  function bootAll(root) {
    const scope = root || document;
    hydrateAll(scope);
    holdBakedFrames(scope);
    initPrecomputeOnce(scope);
    mountHeaderButtons(scope);
    mountHeaderRepoLink(scope);
    hydratePlotly(scope);
    hydrateVega(scope);
    watchSchemeForVega();
    syncMarimoTheme();
    hydrateReleaseDownloads(scope);
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

  // WASM pages that carry an islands JSON payload (build_bootstrap_payload
  // in transforms/wasm.py): once the Pyodide worker is ready, marimo's
  // runtime *materializes* the payload — it replaces every anchored
  // island's <marimo-cell-output> innerHTML with the payload's outputHtml
  // and dispatches `marimo-island-source-changed` on the island. That
  // outputHtml is the build-time markup, so the anywidget / plotly mounts
  // inside it are fresh, un-hydrated divs replacing the ones we hydrated at
  // DOMContentLoaded. Re-run the (idempotent) hydrators on that island. The
  // event is dispatched without `bubbles`, so listen in the capture phase.
  document.addEventListener(
    "marimo-island-source-changed",
    (event) => {
      const island = event.target;
      if (!(island instanceof Element)) return;
      hydrateAll(island);
      hydratePlotly(island);
      hydrateVega(island);
    },
    true
  );
})();
