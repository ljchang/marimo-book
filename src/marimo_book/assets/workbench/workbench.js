// marimo-book workbench — page shell.
//
// Loaded site-wide; a no-op on pages without a `#wb-block` (which
// render_workbench_block in workbench.py emits for pages whose `views`
// include run or edit, or that carry an `assignment:`). On those pages it:
//   - mounts the Read / Run / Edit control (plus a copy-status chip, History
//     and an Assignment toggle) in Material's header, left of the palette
//     toggle;
//   - swaps the content area between the rendered page (`read`) and an
//     <iframe> that loads the mount page (`run` = marimo's present view,
//     `edit` = the editor);
//   - opens the page's assignment — a separate notebook with its own local
//     copy — in a bottom drawer with its own bar (status, grader sign-in,
//     History, Minimize / Hide), so the chapter stays readable above it;
//   - reads the same IndexedDB the mount page writes (same origin) for
//     status, the "new version available" banner, and the history drawer.
//
// Talks to the frames over postMessage only for boot timing / save events.
(function () {
  // One page instance at a time: Material's instant navigation swaps the
  // article without a page load, so the previous instance's window-level
  // listeners and history patch are torn down whenever the page changes —
  // including a move to a page with no workbench at all.
  let current = null; // { bar, teardown }

  function wbInit() {
    const $ = (sel, root) => (root || document).querySelector(sel);
    const bar = $("#wb-toolbar");
    if (current && current.bar === bar) return; // same page, already booted
    if (current) {
      current.teardown();
      current = null;
    }
    if (!bar) return;
    const scope = new AbortController();
    const signal = scope.signal;

    // ---- identity + config from the block ---------------------------------
    const wbRoot = new URL(bar.dataset.wbRoot, location.href); // …/_workbench/
    const wbVersion = bar.dataset.wbV || "";
    const siteRoot = wbRoot.pathname.replace(/_workbench\/$/, "");
    const chapter = {
      // Scoped to the site's path so two books on one origin never share copies.
      nb: siteRoot + bar.dataset.nb,
      src: bar.dataset.src ? new URL(bar.dataset.src, location.href).href : "",
      hash: bar.dataset.hash || "",
      name: bar.dataset.nb.split("/").pop(),
    };
    const views = (bar.dataset.views || "read").split(",").filter(Boolean);
    const canEdit = views.includes("edit");
    const cp = bar.dataset.checkpointMinutes || "10";
    const keep = bar.dataset.maxCheckpoints || "20";

    const asgEl = $("#wb-assignment");
    const assignment = asgEl
      ? {
          nb: siteRoot + asgEl.dataset.nb,
          src: new URL(asgEl.dataset.src, location.href).href,
          hash: asgEl.dataset.hash || "",
          name: asgEl.dataset.nb.split("/").pop(),
          graderServer: asgEl.dataset.graderServer || "",
        }
      : null;

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
      document.addEventListener("DOMContentLoaded", place, { signal });
      setTimeout(place, 300);
    }
    const segGroup = $("#wb-header .wb-seg");
    if (segGroup && views.length < 2) segGroup.hidden = true;
    if (!assignment) $("#wb-asg-toggle")?.remove();

    // ---- wrap the rendered page in #wb-read --------------------------------
    // The block sits ahead of the body in the Markdown; everything after it
    // in the article up to the assignment card is the `read` view. Material
    // appends page metadata (source/date/feedback) after the content — leave
    // those outside too.
    const block = $("#wb-block");
    const read = document.createElement("div");
    read.id = "wb-read";
    let node = block.nextSibling;
    while (node) {
      if (
        node.nodeType === 1 &&
        node.matches("#wb-assignment, #wb-drawer, .md-source-file, .md-source-date, .md-feedback, .md-tags")
      ) {
        break;
      }
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
      historyTitle: $("#wb-history-title"),
      historyList: $("#wb-history-list"),
      previewTitle: $("#wb-preview-title"),
      preview: $("#wb-preview"),
      restore: $("#wb-restore"),
      restoreConfirm: $("#wb-restore-confirm"),
      previewDownload: $("#wb-preview-download"),
      note: $("#wb-note"),
      asgToggle: $("#wb-asg-toggle"),
      asgStart: $("#wb-asg-start"),
      asgStatus: $("#wb-asg-status"),
      asgCardStatus: $("#wb-asg-card-status"),
      asgFrameBox: $("#wb-asg-frame"),
      drawer: $("#wb-drawer"),
      grader: $("#wb-grader"),
    };

    let state = "read";
    let frame = null;
    let frameView = null;
    let frameT0 = 0;
    let asgFrame = null;
    let asgT0 = 0;
    let historyTarget = chapter; // which copy the drawer shows
    let selectedSnap = null;
    let undoSnap = null;

    const themeName = () => (document.body.getAttribute("data-md-color-scheme") === "slate" ? "dark" : "light");
    const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

    function frameUrl(target, view) {
      const u = new URL("index.html", wbRoot);
      // The mount page and the scripts it loads are a matched set; without
      // this a reader holding the pre-upgrade page in cache would pair it with
      // the new scripts.
      if (wbVersion) u.searchParams.set("v", wbVersion);
      u.searchParams.set("nb", target.nb);
      u.searchParams.set("src", target.src);
      u.searchParams.set("hash", target.hash);
      u.searchParams.set("theme", themeName());
      u.searchParams.set("cp", cp);
      u.searchParams.set("keep", keep);
      if (view === "run") {
        u.searchParams.set("view-as", "present");
        u.searchParams.set("persist", "0"); // run never creates or saves a copy
      }
      if (new URL(location.href).searchParams.get("wblog") === "1") u.searchParams.set("wblog", "1");
      return u.toString();
    }

    function makeFrame(target, view) {
      const f = document.createElement("iframe");
      f.src = frameUrl(target, view);
      f.title = view === "run" ? "Notebook (run)" : target === chapter ? "Notebook (edit)" : "Assignment";
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
          frame = makeFrame(chapter, next);
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
    window.addEventListener(
      "popstate",
      (e) => {
        // Only our own entries carry wbView; Material's hash bookkeeping is ignored.
        if (e.state && typeof e.state.wbView === "string") setState(e.state.wbView, false);
      },
      { signal }
    );
    // Material's navigation.tracking rewrites the URL (path + hash) as the
    // reader scrolls, dropping ?view=; put it back so a reload lands in the
    // same state, while a nav click (a plain URL) still opens the page view.
    const origReplace = history.replaceState.bind(history);
    current = {
      bar,
      teardown: () => {
        scope.abort();
        history.replaceState = origReplace;
      },
    };
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
      if (canEdit) {
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
      if (assignment) {
        const aws = await WB.getWorkspace(assignment.nb);
        const behind = Boolean(aws && aws.baseHash !== assignment.hash);
        const label = aws
          ? `In progress · ${WB.timeAgo(aws.updatedAt)}${aws.lastSubmittedAt ? ` · submitted ${WB.fmt(aws.lastSubmittedAt)}` : ""}${behind ? " · update available" : ""}`
          : "Not started";
        $("#wb-asg-update").hidden = !behind;
        els.asgStatus.textContent = label;
        els.asgCardStatus.textContent = label;
        els.asgStart.textContent = aws ? "Continue assignment" : "Open assignment";
        if (els.asgToggle) {
          els.asgToggle.innerHTML = `${aws ? '<span class="dot"></span>' : ""}Assignment`;
          els.asgToggle.title = aws ? `Assignment: ${label}` : "Open the assignment in a drawer";
        }
      }
    }

    async function checkUpdate() {
      if (!canEdit) return;
      const ws = await WB.getWorkspace(chapter.nb);
      const behind = Boolean(ws && ws.baseHash !== chapter.hash);
      els.banner.hidden = !behind;
      if (behind) els.bannerText.innerHTML = "<strong>This notebook was updated.</strong> Your work is saved.";
    }

    async function fetchPublished(target) {
      const res = await fetch(target.src, { cache: "no-store" });
      return res.text();
    }

    function reloadFrame(target) {
      if (target === chapter) {
        if (!frame) return;
        frameT0 = performance.now();
        els.boot.textContent = "Restarting the notebook…";
        frame.src = frame.src;
      } else if (asgFrame) {
        asgT0 = performance.now();
        asgFrame.src = asgFrame.src;
      }
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

    // ---- update transaction (chapter or assignment copy) -------------------
    // Whole-notebook replace with a snapshot on each side, so it is always
    // undoable. Cell-level merging is a later step.
    let undoTarget = null;
    async function updateTarget(target) {
      const ws = await WB.getWorkspace(target.nb);
      if (!ws) return;
      const published = await fetchPublished(target);
      const now = Date.now();
      undoSnap = { notebookId: target.nb, ts: now, reason: "before-update", hash: ws.baseHash, source: ws.workingSource, baseSource: ws.baseSource };
      undoTarget = target;
      await WB.addSnapshot(undoSnap);
      Object.assign(ws, { workingSource: published, baseSource: published, baseHash: target.hash, updatedAt: now + 1 });
      await WB.putWorkspace(ws);
      await WB.addSnapshot({ notebookId: target.nb, ts: now + 1, reason: "after-update", hash: target.hash, source: published });
      if (target === chapter) els.banner.hidden = true;
      reloadFrame(target);
      refreshStatus();
      showToast(
        target === chapter
          ? "Updated to the published version. Your previous copy is in History."
          : "Assignment updated to the published version. Your previous copy is in its History.",
        { label: "Undo", fn: undoUpdate }
      );
    }
    $("#wb-update").addEventListener("click", () => updateTarget(chapter));
    if (assignment) $("#wb-asg-update").addEventListener("click", () => updateTarget(assignment));

    async function undoUpdate() {
      if (!undoSnap || !undoTarget) return;
      const target = undoTarget;
      const ws = await WB.getWorkspace(target.nb);
      const now = Date.now();
      await WB.addSnapshot({ notebookId: target.nb, ts: now, reason: "before-restore", hash: ws.baseHash, source: ws.workingSource });
      Object.assign(ws, { workingSource: undoSnap.source, baseSource: undoSnap.baseSource, baseHash: undoSnap.hash, updatedAt: now + 1 });
      await WB.putWorkspace(ws);
      undoSnap = null;
      undoTarget = null;
      reloadFrame(target);
      refreshStatus();
      checkUpdate();
    }

    $("#wb-later").addEventListener("click", () => (els.banner.hidden = true));
    $("#wb-changes").addEventListener("click", async () => {
      historyTarget = chapter;
      await openHistory();
      const ws = await WB.getWorkspace(chapter.nb);
      showDiff("Published version vs. your copy", ws ? ws.workingSource : "", await fetchPublished(chapter));
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
        download(chapter.name, ws.workingSource);
      },
      { capture: true, signal }
    );

    // ---- history drawer (chapter or assignment copy) -----------------------
    async function openHistory() {
      els.history.hidden = false;
      els.historyTitle.textContent =
        historyTarget === chapter ? "Version history" : "Version history · assignment";
      selectedSnap = null;
      els.restore.hidden = true;
      els.restoreConfirm.hidden = true;
      els.previewDownload.hidden = true;
      els.previewTitle.textContent = "Select a version";
      els.preview.textContent = "";
      await renderHistoryList();
    }

    async function renderHistoryList() {
      const ws = await WB.getWorkspace(historyTarget.nb);
      const snaps = await WB.listSnapshots(historyTarget.nb);
      els.historyList.innerHTML = "";
      if (!ws) {
        const li = document.createElement("li");
        li.append(
          document.createElement("span"),
          document.createTextNode(
            historyTarget === chapter
              ? "No local copy yet — open Edit to create one."
              : "Not started yet — open the assignment to create your copy."
          )
        );
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
      const ws = await WB.getWorkspace(historyTarget.nb);
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

    $("#wb-history-btn").addEventListener("click", () => { historyTarget = chapter; openHistory(); });
    $("#wb-history-close").addEventListener("click", () => (els.history.hidden = true));
    $("#wb-save-version").addEventListener("click", async () => {
      const ws = await WB.getWorkspace(historyTarget.nb);
      if (!ws) return;
      await WB.addSnapshot({ notebookId: historyTarget.nb, ts: Date.now(), reason: "manual", hash: ws.baseHash, source: ws.workingSource, note: els.note.value.trim() });
      els.note.value = "";
      renderHistoryList();
    });
    els.restore.addEventListener("click", () => { els.restore.hidden = true; els.restoreConfirm.hidden = false; });
    els.restoreConfirm.addEventListener("click", async () => {
      if (!selectedSnap) return;
      const ws = await WB.getWorkspace(historyTarget.nb);
      const now = Date.now();
      await WB.addSnapshot({ notebookId: historyTarget.nb, ts: now, reason: "before-restore", hash: ws.baseHash, source: ws.workingSource });
      ws.workingSource = selectedSnap.source;
      ws.updatedAt = now + 1;
      if (selectedSnap.reason === "before-update" && selectedSnap.baseSource) {
        ws.baseSource = selectedSnap.baseSource;
        ws.baseHash = selectedSnap.hash;
      }
      await WB.putWorkspace(ws);
      els.restoreConfirm.hidden = true;
      reloadFrame(historyTarget);
      await renderHistoryList();
      refreshStatus();
      checkUpdate();
      showToast("Version restored. The copy you had is in History as “Before restore”.");
    });
    els.previewDownload.addEventListener("click", async () => {
      const ws = await WB.getWorkspace(historyTarget.nb);
      const text = selectedSnap ? selectedSnap.source : ws ? ws.workingSource : "";
      const stem = historyTarget.name.replace(/\.py$/, "");
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
      const target = historyTarget;
      const ws = await WB.getWorkspace(target.nb);
      if (!ws) return;
      const published = await fetchPublished(target);
      const now = Date.now();
      await WB.addSnapshot({ notebookId: target.nb, ts: now, reason: "before-reset", hash: ws.baseHash, source: ws.workingSource });
      Object.assign(ws, { workingSource: published, baseSource: published, baseHash: target.hash, updatedAt: now + 1 });
      await WB.putWorkspace(ws);
      reloadFrame(target);
      await renderHistoryList();
      refreshStatus();
      checkUpdate();
      showToast("Reset to the published version. Your previous copy is in History.");
    });
    twoStep("#wb-forget-btn", "#wb-forget-confirm", async () => {
      const target = historyTarget;
      await WB.forget(target.nb);
      els.history.hidden = true;
      if (target === chapter) {
        if (frame) { frame.remove(); frame = null; frameView = null; }
        setState("read", true);
      } else if (asgFrame) {
        asgFrame.remove();
        asgFrame = null;
        setDrawer("hidden");
      }
      refreshStatus();
      checkUpdate();
      showToast("Your copy and its history were deleted. It starts from the published version again.");
    });

    // ---- assignment drawer -------------------------------------------------
    // A bottom drawer with its own bar (status, grader sign-in, history), so
    // the chapter's header controls stay the chapter's. The iframe is created
    // once and kept alive across minimize/hide — a kernel never restarts by
    // accident; only the published card stays in the article.
    let setDrawer = () => {};
    if (assignment) {
      const drawer = els.drawer;
      const DKEY = "wb:drawer:" + location.pathname;
      const BAR_H = 44;
      const applyDrawerHeight = (px) => {
        const h = Math.max(160, Math.min(px, window.innerHeight * 0.9));
        drawer.style.setProperty("--wb-drawer-h", h + "px");
        try { localStorage.setItem("wb:drawer-h", String(Math.round(h))); } catch (_) {}
      };
      const layoutForDrawer = () => {
        const st = drawer.hidden ? "hidden" : drawer.dataset.state;
        const h = st === "open" ? drawer.getBoundingClientRect().height : st === "min" ? BAR_H : 0;
        document.body.style.paddingBottom = h ? h + "px" : "";
        document.documentElement.style.setProperty("--wb-drawer-reserved", h + "px");
      };
      setDrawer = (st) => {
        if (st === "hidden") drawer.hidden = true;
        else {
          drawer.hidden = false;
          drawer.dataset.state = st;
          if (st === "open" && !asgFrame) {
            asgFrame = makeFrame(assignment, "edit");
            asgT0 = performance.now();
            els.asgFrameBox.appendChild(asgFrame);
          }
        }
        try { sessionStorage.setItem(DKEY, st); } catch (_) {}
        els.asgToggle?.setAttribute("aria-pressed", String(st === "open"));
        // Synchronously (the height is readable at once) and again after the
        // next frame — rAF alone stalls in a background tab.
        layoutForDrawer();
        requestAnimationFrame(layoutForDrawer);
        refreshStatus();
      };
      let savedH = 0;
      try { savedH = Number(localStorage.getItem("wb:drawer-h")) || 0; } catch (_) {}
      applyDrawerHeight(savedH || window.innerHeight * 0.55);

      els.asgStart.addEventListener("click", () => setDrawer("open"));
      els.asgToggle?.addEventListener("click", () =>
        setDrawer(!drawer.hidden && drawer.dataset.state === "open" ? "min" : "open")
      );
      $("#wb-drawer-min").addEventListener("click", () => setDrawer(drawer.dataset.state === "min" ? "open" : "min"));
      $("#wb-drawer-close").addEventListener("click", () => setDrawer("hidden"));
      $("#wb-asg-history").addEventListener("click", () => { historyTarget = assignment; openHistory(); });
      drawer.querySelector(".wb-drawer-bar").addEventListener("dblclick", (e) => {
        if (e.target.closest("button")) return;
        setDrawer(drawer.dataset.state === "min" ? "open" : "min");
      });

      // Drag the handle to resize; double-click it to maximize.
      const handle = $("#wb-drawer-handle");
      let dragY = 0, dragH = 0;
      const onMove = (e) => { applyDrawerHeight(dragH + (dragY - e.clientY)); layoutForDrawer(); };
      const onUp = () => {
        window.removeEventListener("pointermove", onMove);
        window.removeEventListener("pointerup", onUp);
        drawer.classList.remove("dragging");
      };
      handle.addEventListener("pointerdown", (e) => {
        if (drawer.dataset.state !== "open") return;
        dragY = e.clientY;
        dragH = drawer.getBoundingClientRect().height;
        drawer.classList.add("dragging"); // no pointer events on the iframe while dragging
        window.addEventListener("pointermove", onMove, { signal });
        window.addEventListener("pointerup", onUp, { signal });
      });
      handle.addEventListener("dblclick", () => { applyDrawerHeight(window.innerHeight * 0.9); layoutForDrawer(); });
      window.addEventListener("resize", layoutForDrawer, { signal });
      signal.addEventListener("abort", () => {
        document.body.style.paddingBottom = "";
        document.documentElement.style.removeProperty("--wb-drawer-reserved");
      });

      // ---- grader sign-in (same device flow and token key as the widget) ----
      const server = assignment.graderServer;
      const tokenKey = `grader:${server}:token`;
      const readToken = () => {
        try {
          const t = JSON.parse(localStorage.getItem(tokenKey) || "null");
          if (!t || !t.token) return null;
          if (t.expires_at && Date.parse(t.expires_at) < Date.now()) return null;
          return t;
        } catch (_) {
          return null;
        }
      };
      const refreshGrader = () => {
        if (!server) return;
        const t = readToken();
        els.grader.hidden = false;
        els.grader.textContent = t ? `Grader · ${t.netid || "signed in"}` : "Grader · sign in";
        els.grader.classList.toggle("ok", Boolean(t));
        els.grader.title = t ? `Signed in to ${server} as ${t.netid}` : `Sign in to ${server}`;
      };
      const graderApi = async (path, body) => {
        let res;
        try {
          res = await fetch(`${server}/api/v1${path}`, {
            method: "POST",
            headers: { Accept: "application/json", "Content-Type": "application/json" },
            body: JSON.stringify(body),
          });
        } catch (e) {
          throw new Error(`could not reach ${server} (${e.message}) — the grader must allow this site's origin (CORS)`);
        }
        let data = null;
        try { data = await res.json(); } catch (_) {}
        if (!res.ok) {
          const err = (data && data.error) || {};
          throw new Error(err.message || res.statusText || `http ${res.status}`);
        }
        return data;
      };
      const graderSignIn = async () => {
        let tab = null;
        try { tab = window.open("", "_blank"); } catch (_) {}
        els.grader.textContent = "Grader · contacting…";
        let start;
        try {
          start = await graderApi("/auth/device", { client: "marimo-book workbench" });
        } catch (e) {
          if (tab) tab.close();
          refreshGrader();
          showToast(`Sign-in failed: ${e.message}`, null, true);
          return;
        }
        if (tab) { try { tab.location.href = start.verification_url; } catch (_) {} }
        els.grader.textContent = "Grader · waiting…";
        showToast(`Enter code ${start.user_code} in the sign-in tab. Waiting for approval…`, null, true);
        const deadline = Date.now() + (Number(start.expires_in) || 600) * 1000;
        const interval = Math.max(1, Number(start.interval) || 3) * 1000;
        while (Date.now() < deadline && !signal.aborted) {
          await sleep(interval);
          let poll;
          try { poll = await graderApi("/auth/device/token", { device_code: start.device_code }); } catch (_) { continue; }
          if (poll.status === "approved") {
            const expiresAt = new Date(Date.now() + (Number(poll.expires_in) || 28800) * 1000).toISOString();
            localStorage.setItem(tokenKey, JSON.stringify({ token: poll.access_token, netid: poll.netid, expires_at: expiresAt }));
            refreshGrader();
            showToast(`Signed in to the grader as ${poll.netid}.`);
            return;
          }
          if (poll.status === "expired") {
            refreshGrader();
            showToast("The sign-in code expired. Try again.");
            return;
          }
        }
        refreshGrader();
      };
      if (server) {
        els.grader.addEventListener("click", () => {
          const t = readToken();
          if (t) {
            showToast(`Signed in to the grader as ${t.netid || "?"}.`, {
              label: "Sign out",
              fn: () => { localStorage.removeItem(tokenKey); refreshGrader(); },
            });
            return;
          }
          graderSignIn();
        });
        window.addEventListener("storage", (e) => { if (e.key === tokenKey) refreshGrader(); }, { signal });
        refreshGrader();
      }

      let remembered = null;
      try { remembered = sessionStorage.getItem(DKEY); } catch (_) {}
      if (remembered === "open" || remembered === "min") setDrawer(remembered);
      else layoutForDrawer();
    }

    // ---- messages from the frames -------------------------------------------
    window.addEventListener(
      "message",
      (e) => {
        if (e.origin !== location.origin || !e.data || e.data.source !== "wb") return;
        const d = e.data;
        const isChapter = d.nb === chapter.nb;
        const isAssignment = assignment && d.nb === assignment.nb;
        if (!isChapter && !isAssignment) return;
        if (isChapter) {
          const secs = ((performance.now() - frameT0) / 1000).toFixed(1);
          if (d.type === "editor") els.boot.textContent = `Editor ready in ${secs} s — packages installing, cells will run shortly.`;
          if (d.type === "ran") els.boot.textContent = `Editor ready; first output at ${secs} s.`;
          if (d.type === "loaded") checkUpdate();
          // The frame could not read the reader's copy. It boots anyway from
          // the published notebook, but the status line would otherwise sit
          // frozen on whatever it last said, with the failure going nowhere.
          if (d.type === "error") {
            els.boot.textContent =
              "Could not load your saved copy — starting from the published notebook.";
          }
        }
        if (d.type === "submitted" && isAssignment) {
          // The grader widget announced a submission: keep it as a version.
          WB.getWorkspace(assignment.nb).then(async (ws) => {
            if (!ws) return;
            const now = Date.now();
            await WB.addSnapshot({ notebookId: assignment.nb, ts: now, reason: "submission", hash: ws.baseHash, source: ws.workingSource, note: d.note || "" });
            ws.lastSubmittedAt = now;
            await WB.putWorkspace(ws);
            refreshStatus();
          });
        }
        if (d.type === "saved" || d.type === "loaded" || d.type === "created") refreshStatus();
      },
      { signal }
    );

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
