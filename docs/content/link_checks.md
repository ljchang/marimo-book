# Broken-link checking

`marimo-book` supports two layers of link validation, each opt-in:

| Layer | Catches | Tool | Opt-in |
|---|---|---|---|
| **Internal** | In-tree broken page links, missing anchors, missing assets | `mkdocs build --strict` | Add `--strict` to your build command |
| **External** | Dead external URLs (HTTP 404s, DNS errors) | `mkdocs-htmlproofer-plugin` | `pip install 'marimo-book[linkcheck]'` + `check_external_links: true` |

## Internal links

Adding `--strict` to `marimo-book build` turns every mkdocs warning
into a build error:

```bash
marimo-book build --strict
```

Catches:

- `[text](missing-page.md)` when `missing-page.md` isn't in the nav
- `[text](#missing-anchor)` when no header in the page matches
- Images whose `src` doesn't resolve

`marimo-book` already fixes two common false positives automatically:

- `[text](Foo.ipynb)` links are rewritten to `[text](Foo.md)` when
  `Foo.md` exists in the staged tree (handy after migrating from
  Jupyter notebooks).
- `../images/...` paths in flattened `.md` files are rewritten to
  `images/...` so they resolve after the preprocessor stages content
  from `content/foo.md` into `docs/foo.md`.

## External links

The htmlproofer plugin does HEAD/GET checks against the live web for
every `<a href="https://...">` and `<img src="https://...">` at build
time. Enable it in `book.yml`:

```yaml
check_external_links: true
```

And install the extra:

```bash
pip install 'marimo-book[linkcheck]'
```

Then build:

```bash
marimo-book build --strict
```

Expect this to be slow — typically 1–3 seconds per external link. A
book with 100 external references takes 2–5 minutes to validate. **Keep
this off for local dev loops; turn it on in CI for release builds.**

### CI pattern

```yaml
# .github/workflows/release.yml
- run: pip install 'marimo-book[linkcheck]'
- run: |
    # Temporarily enable external checks; restore on exit.
    sed -i 's/check_external_links: false/check_external_links: true/' book.yml
    marimo-book build --strict
```

Or, cleaner, keep it on in `book.yml` and run `marimo-book build
--strict` unconditionally. The linkcheck extra is lightweight
(`mkdocs-htmlproofer-plugin`), so there's no harm in always-on CI.

## False-positive escape hatches

Some sites rate-limit automated HEAD requests; others require cookies.
The `htmlproofer` plugin accepts a per-URL ignore list you can surface
by switching to a full `mkdocs.yml` override (not yet exposed through
`book.yml`). If you hit this, either drop the flag or open an issue on
`marimo-book` asking for an ignore-list field.
