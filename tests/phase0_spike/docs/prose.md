# Prose, math, admonitions

This page is dense on purpose — it exercises everything dartbrains content actually uses.

## Admonitions (Material native, via `pymdownx.blocks.admonition`)

!!! note
    `!!! note` — a plain note.

!!! tip "A tip with a custom title"
    Tips look different from notes. The preprocessor will translate MyST `:::{tip}` into this.

!!! warning
    Warnings should get the orange treatment.

!!! danger
    Danger is red.

!!! important
    Important is its own color.

!!! seealso "See also"
    Admonitions support custom titles.

???+ note "A collapsible, initially-open admonition"
    This uses `pymdownx.details` (the `???+` prefix). The current JB2 pipeline
    emits `:::{admonition} ... :class: dropdown`; our preprocessor will
    translate that to this form.

## Math

Inline math works like $f(x) = \int_{-\infty}^{\infty} \hat f(\xi) e^{2\pi i x \xi}\, d\xi$.

Block math renders with MathJax via `pymdownx.arithmatex`:

$$
\mathbf{y} = X\boldsymbol{\beta} + \boldsymbol{\epsilon}, \qquad
\boldsymbol{\epsilon} \sim \mathcal{N}(0, \sigma^2 I)
$$

An amsmath-style `align` environment:

$$
\begin{align}
\hat{\boldsymbol{\beta}} &= (X^\top X)^{-1} X^\top \mathbf{y} \\
\operatorname{Var}(\hat{\boldsymbol{\beta}}) &= \sigma^2 (X^\top X)^{-1}
\end{align}
$$

## Code

```python
from nltools.data import Brain_Data

brain = Brain_Data("sub-01/func/sub-01_task-rest_bold.nii.gz")
brain.mean().plot()  # static for now; molab button for interactive
```

## Tables

| Chapter          | Type   | Has widgets |
|------------------|--------|-------------|
| Intro            | `.md`  | no          |
| MR Physics 1     | `.py`  | yes         |
| GLM              | `.py`  | yes         |
| Glossary         | `.md`  | no          |
