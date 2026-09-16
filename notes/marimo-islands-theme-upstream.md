# Upstream issue draft: islands can't follow a host page's theme

**Status: drafted, not filed.** Before filing, search `marimo-team/marimo` for
duplicates — "islands render light" in particular may already be reported, in
which case add these findings there instead. Re-check each claim against the
islands version current at that moment; everything below is verified against
`@marimo-team/islands@0.24.2` (source refs are to `marimo-team/marimo`
`frontend/src`, compiled refs to that package's `dist/`).

One issue covering all three bugs: they are one story from an embedder's side,
and how to split the fixes is the maintainers' call, not ours. Paste everything
below the rule.

---

**Title:** Islands: a host page can't theme an embedded notebook (three related
bugs)

## Summary

Embedding a notebook with `MarimoIslandGenerator` in a page that has its own
light/dark theme doesn't work today. The notebook renders light regardless of
the host's theme, and once booted there is no supported way for the host to
change it. Three separate causes, all verified against
`@marimo-team/islands@0.24.2`:

1. Islands compute a theme but never apply it — `ThemeProvider` is app-only.
2. The islands theme atom is cached forever, so a host theme change can't reach it.
3. The Radix dark colour scales are scoped so they can never match.

We work around 1 and 2 in [marimo-book](https://github.com/ljchang/marimo-book)
by setting `document.body`'s `dark` class ourselves and then writing
`data-vscode-theme-kind` — i.e. impersonating the VS Code extension — which
costs us real features (details under bug 2). We'd like to stop doing that, but
what the right API is seems like your call; some options are sketched at the
end.

## Bug 1 — Islands never apply their resolved theme

`frontend/src/theme/useTheme.ts`'s `themeAtom` has an islands branch that infers
a theme from `<body>`: a `dark` / `dark-mode` class, `data-theme`, `data-mode`,
the computed `color-scheme`, finally the background's brightness. That resolved
theme reaches the per-component consumers (`useTheme()` in the Vega component,
mermaid, `JsonOutput`, the data tables, …), but nothing applies it to the
notebook's own chrome.

The component that would is `ThemeProvider`
(`frontend/src/theme/ThemeProvider.tsx`), which stamps `dark` / `dark-theme` on
`document.body`. The provider itself is used only by `frontend/src/mount.tsx` —
the full app. (`core/MarimoApp.tsx` imports from the same module, but takes
`CssVariables`, not the provider.) `core/islands/bootstrap.ts` never mounts it,
and no file under `core/islands/` references `ThemeProvider` or `useTheme` at
all.

That matters because practically every colour token in the bundle resolves
through a `.dark` **ancestor**. From `dist/style.css`:

```css
.marimo { … color-scheme: light }
:is(.marimo .dark, .marimo :root:has(body.dark), .marimo:is(.dark *)) { … color-scheme: dark }
```

with `--background` and friends defined as `light-dark()` values on `.marimo`.
So islands compute a theme and then discard it for everything the reader
actually looks at.

**Repro**

1. Generate an islands page and open it.
2. `document.body.dataset.theme = "dark"` — one of the inputs `themeAtom`
   documents for islands.
3. The theme atom now resolves `"dark"`, but
   `getComputedStyle(document.querySelector(".marimo")).getPropertyValue("--background")`
   is still `#fff` and the cells render light.
4. `document.body.classList.add("dark")` → `--background` becomes `#181c1a` and
   the notebook renders correctly.

Step 4 is the workaround, and an embedder can only find it by reading the
compiled CSS — nothing in the islands docs says the host is responsible for
placing a class.

## Bug 2 — The theme is resolved once, and a host has no way to change it

`themeAtom`'s islands branch reads the DOM inside a derived jotai atom with no
reactive dependency, so jotai caches the first value for the life of the page:

```ts
const themeAtom = atom((get) => {
  if (isIslands()) {
    if (document.body.classList.contains("dark") || …) return "dark";
    // … computed color-scheme, then background brightness
    return "light";
  }
  return get(resolvedMarimoConfigAtom).display.theme;
});
```

The embedded **full app** has the same problem from the other direction:
`__MARIMO_MOUNT_CONFIG__`'s `config.display.theme` (and the `?theme=` query
parameter) is read at mount, with no supported way in afterwards.

The one theme input that *is* reactive is `codeThemeAtom`, fed by a
MutationObserver on `document.body`'s `data-vscode-theme-kind` — and it
overrides everything else:

```ts
export const resolvedThemeAtom = atom((get) => {
  const theme = get(themeAtom);
  const codeTheme = get(codeThemeAtom);
  if (codeTheme !== undefined) return codeTheme;   // ← the only live hook
  const prefersDarkMode = get(prefersDarkModeAtom);
  return theme === "system" ? (prefersDarkMode ? "dark" : "light") : theme;
});
```

So the only way for a host to re-theme a booted notebook is to set
`data-vscode-theme-kind` and pretend to be the VS Code extension. It does work
— it re-themes the things CSS can't reach, including CodeMirror's syntax
colours (hard-coded hex in a JS extension) and the data tables' canvas — but it
also makes `isInVscodeExtension()` (`core/vscode/is-in-vscode.ts`, a bare
`querySelector("[data-vscode-theme-kind]")`) return true, so marimo hides the
data table's row- and column-explorer buttons and zeroes `MAX_HEIGHT_OFFSET`.

That is what marimo-book ships today, for both its islands pages and its
embedded editor, and it is the reason for this issue.

**Repro**

1. Embed a notebook in a page with a theme toggle (islands, or the full app via
   `__MARIMO_MOUNT_CONFIG__`).
2. Change the host's theme by any means the islands inference documents — add
   `dark` to `<body>`, set `data-theme`, flip the computed `color-scheme`.
3. The notebook does not change. Only `data-vscode-theme-kind` moves it.

## Bug 3 — Radix dark colour scales can never match

Independent of the other two: this stays broken even once the host does place
`.dark` correctly, which is how we found it.

`dist/style.css` emits the Radix dark scales as:

```css
.marimo .dark, .marimo .dark-theme { --amber-1: #16120c; … --gray-10: #7b7b7b; … }
```

which requires `.dark` to be a **descendant** of `.marimo`. But the class goes
on `document.body` — by `ThemeProvider` in the app, by the host page for islands
— which is an **ancestor** of every `.marimo` element, so none of those ~30
rules can ever match. The rest of the bundle uses the ancestor form and works:

```css
:is(.marimo .dark, .marimo :root:has(body.dark), .marimo:is(.dark *)) { … }
```

Measured in Chrome on an islands page correctly in dark mode
(`<body class="dark">`, everything else rendering dark):
`getComputedStyle(document.querySelector(".marimo")).getPropertyValue("--gray-10")`
returns `#838383`, the light value. The dark scale's `#7b7b7b` never applies.

It looks like the `.marimo` namespacing prefixer was applied to Radix's own
`.dark, .dark-theme` selectors without the `:is(.dark *)` rewrite the rest of
the CSS receives.

## Possible shapes — entirely your call

Listing these to be concrete about what would unblock embedders, not to propose
a design. Any one of them would let us drop the VS Code impersonation.

**For bug 1** — mount `ThemeProvider` in the islands bootstrap, or have each
island put its own resolved theme class on its container, so the host doesn't
have to know about `.dark` at all.

**For bug 2** — some way to tell a booted notebook its theme changed:

- watch the inputs `themeAtom` already reads: a MutationObserver on
  `document.body` for `class`, `data-theme` and `data-mode`, in the same shape
  as the `setupVsCodeThemeListener` that already exists a few lines below.
  Smallest change, and it makes the documented inputs behave the way an
  embedder would expect;
- or a public setter, e.g. `window.marimo.setTheme("light" | "dark" | "system")`;
- or accept `theme` on the islands mount config and/or make the app's
  `config.display.theme` settable after mount — the only option that also
  covers the embedded full app.

Happy to put up a PR for whichever direction you'd prefer, or for bug 3 on its
own if that's easiest to take separately.
