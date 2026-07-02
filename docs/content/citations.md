# Citations

marimo-book renders pandoc-style citations natively — no mkdocs plugin, no
pandoc install. Point `book.yml` at one or more BibTeX files:

```yaml
bibliography:
  - refs.bib
cite_style: apa   # or: numbered
```

Then cite in any `.md` page or in marimo notebook prose:

```markdown
Emotion has a distributed neural signature [@chang2015].
For statistics background, see [@poldrack2024].
```

which renders as: Emotion has a distributed neural signature [@chang2015].
For statistics background, see [@poldrack2024].

## How it works

- `[@key]` and multi-key `[@a; @b]` groups become inline citations linked
  to a per-page **References** section (appended automatically, or placed
  wherever a standalone `\bibliography` line appears).
- `cite_style: apa` gives author–year inline citations with an
  alphabetized reference list; `numbered` gives `[1]`-style citations
  numbered by first use.
- Citations inside code fences and `` `inline code` `` are left alone, and
  unknown keys stay verbatim in the page — `marimo-book check` reports
  missing `.bib` files as errors and unknown keys as warnings.
- The `.bib` is resolved at finalize time, so editing it never invalidates
  cached notebook renders.
