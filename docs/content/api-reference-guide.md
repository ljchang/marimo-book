# Auto-generated API reference

`marimo-book` can build a Python **API Reference** section straight from your
companion package's docstrings, using
[mkdocstrings](https://mkdocstrings.github.io/) and
[Griffe](https://mkdocstrings.github.io/griffe/).

## Enable it

Install the extra and turn on the flag in `book.yml`:

```bash
pip install 'marimo-book[api]'
```

```yaml
api_docs:
  enabled: true
  packages: ["mypkg"]      # importable / dotted names
  paths: ["../src"]        # optional source dirs, relative to the book root
  docstring_style: google  # google | numpy | sphinx
```

`marimo-book` loads each package, stages one page per public module, and adds
a nested "API Reference" section to your nav. No `:::` directives or TOC edits
needed.

## Where the source comes from

Griffe reads source from `paths` **without installing the package**, so an
adjacent `src/` (monorepo or git submodule) is the simplest setup. You can
also document a package that's installed in the build environment — including
one pinned from another GitHub repo as a book dependency
(`pip install 'git+https://github.com/org/pkg@v1.2'`) — by listing its import
name in `packages` and omitting `paths`.

## Tuning the output

`api_docs.options` passes straight through to the mkdocstrings Python handler,
so anything that handler supports works:

```yaml
api_docs:
  enabled: true
  packages: ["mypkg"]
  exclude: ["mypkg.tests*"]        # skip modules by dotted-path glob
  inventories:                     # cross-link to other libraries' docs
    - "https://docs.python.org/3/objects.inv"
  options:
    members_order: source
    show_root_full_path: false
    merge_init_into_class: true
```

marimo-book's defaults (`show_source`, `show_root_heading`,
`show_submodules: false`, plus your `docstring_style`) are merged first; your
`options` keys win.
