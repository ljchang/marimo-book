// MathJax config expected by pymdownx.arithmatex (generic mode).
window.MathJax = {
  tex: {
    inlineMath: [["\\(", "\\)"]],
    displayMath: [["\\[", "\\]"]],
    processEscapes: true,
    processEnvironments: true
  },
  options: {
    ignoreHtmlClass: ".*|",
    processHtmlClass: "arithmatex"
  }
};

// Belt-and-suspenders typeset boot, mirroring the precompute shim.
// Material's `document$` is an RxJS Subject (not BehaviorSubject), so a
// late subscriber misses the initial emission — that's exactly what
// happens on a direct page load *and* on every instant-nav swap, where
// the new page body lands before any subscriber is ready. With only
// `document$.subscribe`, MathJax silently never runs and arithmatex
// spans render as raw `\(...\)` LaTeX text.
//
// Fix: also typeset on DOMContentLoaded / immediate, *and* on every
// `document$` emission. typesetPromise is idempotent over already-
// rendered output, so calling it twice on the same page is harmless.
function typesetMath() {
  if (window.MathJax && MathJax.typesetPromise) {
    MathJax.typesetPromise();
  }
}
if (document.readyState === "loading") {
  document.addEventListener("DOMContentLoaded", typesetMath);
} else {
  typesetMath();
}
if (typeof document$ !== "undefined" && document$.subscribe) {
  document$.subscribe(typesetMath);
}
