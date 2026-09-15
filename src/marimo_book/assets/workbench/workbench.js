// marimo-book workbench — page shell.
//
// Loaded site-wide; a no-op on pages without a `#wb-block` (which
// render_workbench_block in workbench.py emits for pages whose `views`
// include run or edit). On those pages it:
//   - mounts the Read / Run / Edit control (plus a copy-status chip and
//     History) in Material's header, left of the palette toggle;
//   - swaps the content area between the rendered page (`read`) and an
//     <iframe> that loads the mount page (`run` = marimo's present view,
//     `edit` = the editor);
//   - reads the same IndexedDB the mount page writes (same origin) for
//     status, the "new version available" banner, and the history drawer.
//
// Talks to the frame over postMessage only for boot timing / save events.
(function () {
  function wbInit() {
    const $ = (sel, root) => (root || document).querySelector(sel);
    const bar = $("#wb-toolbar");
    if (!bar || bar.dataset.wbInit) return;
    bar.dataset.wbInit = "1";

    // ---- identity + config from the block ---------------------------------
    const wbRoot = new URL(bar.dataset.wbRoot, location.href); // …/_workbench/
    const siteRoot = wbRoot.pathname.replace(/_workbench\/$/, "");
    const chapter = {
      // Scoped to the site's path so two books on one origin never share copies.
      nb: siteRoot + bar.dataset.nb,
      src: new URL(bar.dataset.src, location.href).href,
      hash: bar.dataset.hash,
    };
    const views = (bar.dataset.views || "read").split(",").filter(Boolean);
    const canEdit = views.includes("edit");
    const cp = bar.dataset.checkpointMinutes || "10";
    const keep = bar.dataset.maxCheckpoints || "20";

    // ---- header controls ---------------------------------------------------
    document.querySelectorAll("#wb-header").forEach((el) => el.remove());
    const tpl = $("#wb-header-tpl");
    const headerInner = document.querySelector(".md-header__inner");
    if (tpl && headerInner) {
      const group = tpl.content.firstElementChild.cloneNode(true);
      const place = () => {
        const anchor =
          headerInner.querySelector(".md-header__option") ||
          headerInner.querySelector(".marimo-book-buttons--header") ||
          headerInner.querySelector('[data-md-component="search"]') ||
          headerInner.querySelector(".md-header__source");
        if (anchor && group.nextElementSibling !== anchor) headerInner.insertBefore(group, anchor);
        else if (!anchor && !group.parentNode) headerInner.appendChild(group);
      };
      place();
      // marimo_book.js clones the launch buttons into the header on
      // DOMContentLoaded; keep our group to their left.
      document.addEventListener("DOMContentLoaded", place);
      setTimeout(place, 300);
    }
    const segGroup = $("#wb-header .wb-seg");
    if (segGroup && views.length < 2) segGroup.hidden = true;

    // ---- wrap the rendered page in #wb-read --------------------------------
    // The block sits ahead of the body in the Markdown; everything after it
    // in the article is the `read` view. Material appends page metadata
    // (source/date/feedback) after the content — leave those outside.
    const block = $("#wb-block");
    const read = document.createElement("div");
    read.id = "wb-read";
    let node = block.nextSibling;
    while (node) {
      if (node.nodeType === 1 && node.matches(".md-source-file, .md-source-date, .md-feedback, .md-tags")) break;
      const next = node.nextSibling;
      read.appendChild(node);
      node = next;
    }
    block.after(read);

    const els = {
      read,
      frame: $("#wb-frame"),
      boot: $("#wb-boot"),
      status: $("#wb-status"),
      banner: $("#wb-banner"),
      bannerText: $("#wb-banner-text"),
      toast: $("#wb-toast"),
      toastText: $("#wb-toast-text"),
      history: $("#wb-history"),
      historyList: $("#wb-history-list"),
      previewTitle: $("#wb-preview-title"),
      preview: $("#wb-preview"),
      restore: $("#wb-restore"),
      restoreConfirm: $("#wb-restore-confirm"),
      previewDownload: $("#wb-preview-download"),
      note: $("#wb-note"),
    };

    let state = "read";
    let frame = null;
    let frameView = null;
    let frameT0 = 0;
    let selectedSnap = null;
    let undoSnap = null;

    const themeName = () => (document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light");
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    function frameUrl(view) {
      const u = new URL("index.html", wbRoot);
      u.searchParams.set("nb", chapter.nb);
      u.searchParams.set("src", chapter.src);
      u.searchParams.set("hash", chapter.hash);
      u.searchParams.set("theme", themeName());
      u.searchParams.set("cp", cp);
      u.searchParams.set("keep", keep);
      if (view === "run") u.searchParams.set("view-as", "present");
      if (new URL(location.href).searchParams.get("wblog") === "1") u.searchParams.set("wblog", "1");
      return u.toString();
    }

    function makeFrame(view) {
      const f = document.createElement("iframe");
      f.src = frameUrl(view);
      f.title = view === "run" ? "Notebook (run)" : "Notebook (edit)";
      f.setAttribute("allow", "clipboard-read; clipboard-write; fullscreen");
      return f;
    }

    // ---- states ------------------------------------------------------------
    function setState(next, push) {
      if (!views.includes(next)) next = views.includes("read") ? "read" : views[0];
      state = next;
      for (const b of document.querySelectorAll("#wb-header .wb-seg-btn")) {
        b.setAttribute("aria-pressed", String(b.dataset.view === next));
      }
      if (next === "read") {
        els.read.hidden = false;
        els.frame.hidden = true;
      } else {
        els.read.hidden = true;
        els.frame.hidden = false;
        if (!frame || frameView !== next) {
          if (frame) frame.remove();
          frame = makeFrame(next);
          frameView = next;
          frameT0 = performance.now();
          els.boot.textContent = "Starting the notebook…";
          els.frame.prepend(frame);
        }
      }
      if (push) {
        const u = new URL(location.href);
        if (next === "read") u.searchParams.delete("view");
        else u.searchParams.set("view", next);
        history.pushState({ wbView: next }, "", u.toString());
      }
    }

    for (const b of document.querySelectorAll("#wb-header .wb-seg-btn")) {
      b.addEventListener("click", () => setState(b.dataset.view, true));
    }
    window.addEventListener("popstate", (e) => {
      // Only our own entries carry wbView; Material's hash bookkeeping is ignored.
      if (e.state && typeof e.state.wbView === "string") setState(e.state.wbView, false);
    });
    // Material's navigation.tracking rewrites the URL (path + hash) as the
    // reader scrolls, dropping ?view=; put it back so a reload lands in the
    // same state, while a nav click (a plain URL) still opens the page view.
    const origReplace = history.replaceState.bind(history);
    history.replaceState = (st, title, url) => {
      if (url && state !== "read") {
        const u = new URL(url, location.href);
        if (!u.searchParams.has("view")) {
          u.searchParams.set("view", state);
          url = u.toString();
        }
      }
      return origReplace(st, title, url);
    };

    // ---- status + banner ---------------------------------------------------
    async function refreshStatus() {
      if (!canEdit) return; // run never creates a copy: nothing to show
      const ws = await WB.getWorkspace(chapter.nb);
      els.status.hidden = false;
      $("#wb-history-btn").hidden = false;
      if (!ws) {
        els.status.textContent = "published";
        els.status.title = "You are reading the published version; no local copy yet";
      } else {
        const behind = ws.baseHash !== chapter.hash;
        els.status.innerHTML = `<span class="dot"></span>your copy · ${WB.timeAgo(ws.updatedAt)}${behind ? " · update available" : ""}`;
        els.status.title = `Your local copy, last edited ${WB.fmt(ws.updatedAt)}`;
      }
    }

    async function checkUpdate() {
      const ws = await WB.getWorkspace(chapter.nb);
      const behind = Boolean(ws && ws.baseHash !== chapter.hash);
      els.banner.hidden = !behind;
      if (behind) els.bannerText.innerHTML = "<strong>This notebook was updated.</strong> Your work is saved.";
    }

    async function fetchPublished() {
      const res = await fetch(chapter.src, { cache: "no-store" });
      return res.text();
    }

    function reloadFrame() {
      if (!frame) return;
      frameT0 = performance.now();
      els.boot.textContent = "Restarting the notebook…";
      frame.src = frame.src;
    }

    let toastAction = null;
    function showToast(text, action, sticky) {
      els.toastText.textContent = text;
      const btn = $("#wb-toast-action");
      toastAction = action || null;
      btn.hidden = !action;
      if (action) btn.textContent = action.label;
      els.toast.hidden = false;
      clearTimeout(showToast._t);
      if (!sticky) showToast._t = setTimeout(() => (els.toast.hidden = true), 12000);
    }
    $("#wb-toast-action").addEventListener("click", () => {
      const a = toastAction;
      els.toast.hidden = true;
      if (a) a.fn();
    });

    // ---- update transaction ------------------------------------------------
    // Whole-notebook replace with a snapshot on each side, so it is always
    // undoable. Cell-level merging is a later step.
    $("#wb-update").addEventListener("click", async () => {
      const ws = await WB.getWorkspace(chapter.nb);
      if (!ws) return;
      const published = await fetchPublished();
      const now = Date.now();
      undoSnap = { notebookId: chapter.nb, ts: now, reason: "before-update", hash: ws.baseHash, source: ws.workingSource, baseSource: ws.baseSource };
      await WB.addSnapshot(undoSnap);
      Object.assign(ws, { workingSource: published, baseSource: published, baseHash: chapter.hash, updatedAt: now + 1 });
      await WB.putWorkspace(ws);
      await WB.addSnapshot({ notebookId: chapter.nb, ts: now + 1, reason: "after-update", hash: chapter.hash, source: published });
      els.banner.hidden = true;
      reloadFrame();
      refreshStatus();
      showToast("Updated to the published version. Your previous copy is in History.", { label: "Undo", fn: undoUpdate });
    });

    async function undoUpdate() {
      if (!undoSnap) return;
      const ws = await WB.getWorkspace(chapter.nb);
      const now = Date.now();
      await WB.addSnapshot({ notebookId: chapter.nb, ts: now, reason: "before-restore", hash: ws.baseHash, source: ws.workingSource });
      Object.assign(ws, { workingSource: undoSnap.source, baseSource: undoSnap.baseSource, baseHash: undoSnap.hash, updatedAt: now + 1 });
      await WB.putWorkspace(ws);
      undoSnap = null;
      reloadFrame();
      refreshStatus();
      checkUpdate();
    }

    $("#wb-later").addEventListener("click", () => (els.banner.hidden = true));
    $("#wb-changes").addEventListener("click", async () => {
      await openHistory();
      const ws = await WB.getWorkspace(chapter.nb);
      showDiff("Published version vs. your copy", ws ? ws.workingSource : "", await fetchPublished());
    });

    // ---- download: the header icon serves the copy when one exists ----------
    function download(name, text) {
      const a = document.createElement("a");
      a.href = URL.createObjectURL(new Blob([text], { type: "text/x-python" }));
      a.download = name;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 2000);
    }
    document.addEventListener(
      "click",
      async (e) => {
        const a = e.target.closest && e.target.closest("a.marimo-book-button-download");
        if (!a || !canEdit) return;
        const ws = await WB.getWorkspace(chapter.nb);
        if (!ws) return;
        e.preventDefault();
        download(bar.dataset.nb.split("/").pop(), ws.workingSource);
      },
      true
    );

    // ---- history drawer ----------------------------------------------------
    async function openHistory() {
      els.history.hidden = false;
      selectedSnap = null;
      els.restore.hidden = true;
      els.restoreConfirm.hidden = true;
      els.previewDownload.hidden = true;
      els.previewTitle.textContent = "Select a version";
      els.preview.textContent = "";
      await renderHistoryList();
    }

    async function renderHistoryList() {
      const ws = await WB.getWorkspace(chapter.nb);
      const snaps = await WB.listSnapshots(chapter.nb);
      els.historyList.innerHTML = "";
      if (!ws) {
        const li = document.createElement("li");
        li.append(document.createElement("span"), document.createTextNode("No local copy yet — open Edit to create one."));
        els.historyList.appendChild(li);
        return;
      }
      const addItem = (label, when, isNow, onClick) => {
        const li = document.createElement("li");
        const dot = document.createElement("span");
        dot.className = isNow ? "dot now" : "dot";
        const body = document.createElement("div");
        body.textContent = label;
        const small = document.createElement("small");
        small.textContent = when;
        body.appendChild(small);
        li.append(dot, body);
        li.addEventListener("click", () => {
          onClick();
          for (const x of els.historyList.children) x.removeAttribute("aria-selected");
          li.setAttribute("aria-selected", "true");
        });
        els.historyList.appendChild(li);
      };
      addItem("Current", WB.fmt(ws.updatedAt), true, () => selectSnap(null, ws.workingSource, "Current copy"));
      for (const s of snaps) {
        const label = (WB.REASON_LABEL[s.reason] || s.reason) + (s.note ? " — " + s.note : "");
        addItem(label, WB.fmt(s.ts), false, () => selectSnap(s, s.source, `${label} · ${WB.fmt(s.ts)}`));
      }
    }

    async function selectSnap(snap, source, title) {
      selectedSnap = snap;
      const ws = await WB.getWorkspace(chapter.nb);
      if (snap && ws) showDiff(title + " (vs. current)", ws.workingSource, source);
      else {
        els.previewTitle.textContent = title;
        els.preview.textContent = source;
      }
      els.restore.hidden = !snap;
      els.restoreConfirm.hidden = true;
      els.previewDownload.hidden = false;
    }

    // Minimal line diff (LCS) — enough to show what a version changes.
    function showDiff(title, a, b) {
      const A = a.split("\n"), B = b.split("\n");
      const n = A.length, m = B.length;
      els.previewTitle.textContent = title;
      if (n * m > 16_000_000) {
        els.preview.textContent = b;
        return;
      }
      const dp = Array.from({ length: n + 1 }, () => new Uint16Array(m + 1));
      for (let i = n - 1; i >= 0; i--) {
        for (let j = m - 1; j >= 0; j--) {
          dp[i][j] = A[i] === B[j] ? dp[i + 1][j + 1] + 1 : Math.max(dp[i + 1][j], dp[i][j + 1]);
        }
      }
      const frag = document.createDocumentFragment();
      let i = 0, j = 0, changed = 0;
      const line = (cls, t) => {
        const s = document.createElement("span");
        if (cls) s.className = cls;
        s.textContent = (cls === "add" ? "+ " : cls === "del" ? "- " : "  ") + t + "\n";
        frag.appendChild(s);
      };
      while (i < n && j < m) {
        if (A[i] === B[j]) { line("", A[i]); i++; j++; }
        else if (dp[i + 1][j] >= dp[i][j + 1]) { line("del", A[i]); i++; changed++; }
        else { line("add", B[j]); j++; changed++; }
      }
      while (i < n) { line("del", A[i++]); changed++; }
      while (j < m) { line("add", B[j++]); changed++; }
      els.preview.innerHTML = "";
      els.preview.appendChild(frag);
      els.previewTitle.textContent = `${title} · ${changed} changed line${changed === 1 ? "" : "s"}`;
    }

    $("#wb-history-btn").addEventListener("click", openHistory);
    $("#wb-history-close").addEventListener("click", () => (els.history.hidden = true));
    $("#wb-save-version").addEventListener("click", async () => {
      const ws = await WB.getWorkspace(chapter.nb);
      if (!ws) return;
      await WB.addSnapshot({ notebookId: chapter.nb, ts: Date.now(), reason: "manual", hash: ws.baseHash, source: ws.workingSource, note: els.note.value.trim() });
      els.note.value = "";
      renderHistoryList();
    });
    els.restore.addEventListener("click", () => { els.restore.hidden = true; els.restoreConfirm.hidden = false; });
    els.restoreConfirm.addEventListener("click", async () => {
      if (!selectedSnap) return;
      const ws = await WB.getWorkspace(chapter.nb);
      const now = Date.now();
      await WB.addSnapshot({ notebookId: chapter.nb, ts: now, reason: "before-restore", hash: ws.baseHash, source: ws.workingSource });
      ws.workingSource = selectedSnap.source;
      ws.updatedAt = now + 1;
      if (selectedSnap.reason === "before-update" && selectedSnap.baseSource) {
        ws.baseSource = selectedSnap.baseSource;
        ws.baseHash = selectedSnap.hash;
      }
      await WB.putWorkspace(ws);
      els.restoreConfirm.hidden = true;
      reloadFrame();
      await renderHistoryList();
      refreshStatus();
      checkUpdate();
      showToast("Version restored. The copy you had is in History as “Before restore”.");
    });
    els.previewDownload.addEventListener("click", async () => {
      const ws = await WB.getWorkspace(chapter.nb);
      const text = selectedSnap ? selectedSnap.source : ws ? ws.workingSource : "";
      const stem = bar.dataset.nb.split("/").pop().replace(/\.py$/, "");
      download(stem + (selectedSnap ? `-${selectedSnap.ts}` : "") + ".py", text);
    });

    // Two-step confirms for the destructive actions in the drawer footer.
    function twoStep(btnId, confirmId, fn) {
      const btn = $(btnId), confirm = $(confirmId);
      let timer = null;
      btn.addEventListener("click", () => {
        btn.hidden = true;
        confirm.hidden = false;
        clearTimeout(timer);
        timer = setTimeout(() => { btn.hidden = false; confirm.hidden = true; }, 6000);
      });
      confirm.addEventListener("click", async () => {
        clearTimeout(timer);
        btn.hidden = false;
        confirm.hidden = true;
        await fn();
      });
    }
    twoStep("#wb-reset-btn", "#wb-reset-confirm", async () => {
      const ws = await WB.getWorkspace(chapter.nb);
      if (!ws) return;
      const published = await fetchPublished();
      const now = Date.now();
      await WB.addSnapshot({ notebookId: chapter.nb, ts: now, reason: "before-reset", hash: ws.baseHash, source: ws.workingSource });
      Object.assign(ws, { workingSource: published, baseSource: published, baseHash: chapter.hash, updatedAt: now + 1 });
      await WB.putWorkspace(ws);
      reloadFrame();
      await renderHistoryList();
      refreshStatus();
      checkUpdate();
      showToast("Reset to the published version. Your previous copy is in History.");
    });
    twoStep("#wb-forget-btn", "#wb-forget-confirm", async () => {
      await WB.forget(chapter.nb);
      els.history.hidden = true;
      if (frame) { frame.remove(); frame = null; frameView = null; }
      setState("read", true);
      refreshStatus();
      checkUpdate();
      showToast("Your copy and its history were deleted. Edit starts from the published version again.");
    });

    // ---- messages from the frame -------------------------------------------
    window.addEventListener("message", (e) => {
      if (e.origin !== location.origin || !e.data || e.data.source !== "wb" || e.data.nb !== chapter.nb) return;
      const d = e.data;
      const secs = ((performance.now() - frameT0) / 1000).toFixed(1);
      if (d.type === "editor") els.boot.textContent = `Editor ready in ${secs} s — packages installing, cells will run shortly.`;
      if (d.type === "ran") els.boot.textContent = `Editor ready; first output at ${secs} s.`;
      if (d.type === "saved" || d.type === "loaded" || d.type === "created") refreshStatus();
      if (d.type === "loaded") checkUpdate();
    });

    // ---- boot --------------------------------------------------------------
    setState(new URL(location.href).searchParams.get("view") || bar.dataset.openIn || "read", false);
    refreshStatus();
    checkUpdate();
  }

  // Material's navigation.instant swaps <main> without a page load; document$
  // fires on every such navigation, so the shell boots once per page either way.
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", wbInit);
  else wbInit();
  if (typeof document$ !== "undefined" && document$.subscribe) document$.subscribe(() => wbInit());
})();
