// marimo-book workbench — shared IndexedDB layer used by the page shell and the mount page.
// One database per origin, two object stores: workspaces (working copy per notebook)
// and snapshots (immutable versions, keyed by [notebookId, ts]).
(function () {
  const DB_NAME = "marimo-book";
  const DB_VERSION = 1;

  function openDB() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open(DB_NAME, DB_VERSION);
      req.onupgradeneeded = () => {
        const db = req.result;
        if (!db.objectStoreNames.contains("workspaces")) {
          db.createObjectStore("workspaces", { keyPath: "notebookId" });
        }
        if (!db.objectStoreNames.contains("snapshots")) {
          const s = db.createObjectStore("snapshots", { keyPath: ["notebookId", "ts"] });
          s.createIndex("byNotebook", "notebookId", { unique: false });
        }
      };
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  }

  async function run(storeName, mode, fn) {
    const db = await openDB();
    try {
      return await new Promise((resolve, reject) => {
        const tx = db.transaction(storeName, mode);
        const req = fn(tx.objectStore(storeName));
        tx.oncomplete = () => resolve(req ? req.result : undefined);
        tx.onerror = () => reject(tx.error);
        tx.onabort = () => reject(tx.error);
      });
    } finally {
      db.close();
    }
  }

  const WB = {
    getWorkspace: (id) => run("workspaces", "readonly", (s) => s.get(id)),
    putWorkspace: (ws) => run("workspaces", "readwrite", (s) => s.put(ws)),
    deleteWorkspace: (id) => run("workspaces", "readwrite", (s) => s.delete(id)),

    addSnapshot: (snap) => run("snapshots", "readwrite", (s) => s.put(snap)),
    getSnapshot: (id, ts) => run("snapshots", "readonly", (s) => s.get([id, ts])),
    deleteSnapshot: (id, ts) => run("snapshots", "readwrite", (s) => s.delete([id, ts])),
    listSnapshots: async (id) => {
      const all = await run("snapshots", "readonly", (s) => s.index("byNotebook").getAll(id));
      return (all || []).sort((a, b) => b.ts - a.ts);
    },
    pruneCheckpoints: async (id, keep) => {
      const cps = (await WB.listSnapshots(id)).filter((s) => s.reason === "checkpoint");
      for (const s of cps.slice(keep)) await WB.deleteSnapshot(id, s.ts);
    },
    forget: async (id) => {
      for (const s of await WB.listSnapshots(id)) await WB.deleteSnapshot(id, s.ts);
      await WB.deleteWorkspace(id);
    },

    sha256: async (text) => {
      const buf = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(text));
      return [...new Uint8Array(buf)].map((b) => b.toString(16).padStart(2, "0")).join("");
    },
    timeAgo: (ts) => {
      const s = Math.max(0, (Date.now() - ts) / 1000);
      if (s < 60) return "just now";
      if (s < 3600) return `${Math.floor(s / 60)} min ago`;
      if (s < 86400) return `${Math.floor(s / 3600)} h ago`;
      return new Date(ts).toLocaleDateString(undefined, { month: "short", day: "numeric" });
    },
    fmt: (ts) =>
      new Date(ts).toLocaleString(undefined, { month: "short", day: "numeric", hour: "numeric", minute: "2-digit" }),
    REASON_LABEL: {
      initial: "First opened",
      checkpoint: "Checkpoint",
      manual: "Saved version",
      "before-update": "Before update",
      "after-update": "Updated",
      "before-restore": "Before restore",
      "before-reset": "Before reset",
      submission: "Submitted",
    },
  };

  window.WB = WB;
})();
