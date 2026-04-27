# Deploying

`marimo-book build` produces a `_site/` directory containing a
self-contained static site: `index.html`, CSS, JS, your `images/` and
other asset directories. Any static host will serve it.

## GitHub Pages (recommended default)

`marimo-book new` scaffolds a ready-to-use workflow at
`.github/workflows/deploy.yml` that deploys on every push to `main`.
Steps:

1. Enable GitHub Pages on your repo: `Settings → Pages → Source: GitHub
   Actions`.
2. Push a commit to `main`.
3. First deploy takes ~1–2 minutes. Subsequent deploys are incremental.

The scaffolded workflow does the minimum — it assumes `env` mode
dependencies. If your notebooks need extra packages, uncomment the
"Install notebook dependencies" step:

```yaml
- name: Install notebook dependencies
  run: pip install -r requirements.txt
```

Or if you're using `sandbox` mode, add a `uv` install step and pass
`--sandbox` to the build:

```yaml
- uses: astral-sh/setup-uv@v3
- run: pip install marimo-book
- run: marimo-book build --sandbox --strict
```

## Custom domain

Drop a `CNAME` file at your **book root** (next to `book.yml`) with a
single line containing your apex domain — e.g.:

```
mybook.org
```

The preprocessor copies it into the staged docs tree on every build,
so mkdocs ships it as `_site/CNAME`. GitHub Pages reads that file on
each redeploy and keeps the custom-domain setting wired up.

DNS at your registrar:

- **Apex** (`mybook.org`) — four `A` records pointing at GitHub Pages:
  `185.199.108.153`, `185.199.109.153`, `185.199.110.153`,
  `185.199.111.153`.
- **`www`** subdomain — one `CNAME` → `<your-username>.github.io`.

Then in repo Settings → Pages, set Custom domain to `mybook.org`. Once
GitHub provisions the Let's Encrypt cert (a few minutes after DNS
verifies), tick "Enforce HTTPS". The marimo-book docs site uses this
exact setup at [marimobook.org](https://marimobook.org/).

## Netlify

Build command: `pip install marimo-book && marimo-book build --strict`

Publish directory: `_site`

Python version: set via `runtime.txt` or Netlify's environment variable
`PYTHON_VERSION=3.13`.

## Cloudflare Pages

Same as Netlify — build command and publish directory. Cloudflare Pages
auto-detects `pyproject.toml` if present.

## Self-host

```bash
marimo-book build --strict
# Serve _site/ with any static server:
python -m http.server 8080 --directory _site
# or caddy file-server -listen :8080 -root _site
# or nginx, s3 sync to a bucket + CloudFront, etc.
```

## Strict mode for releases

Always build with `--strict` for publishes:

```bash
marimo-book build --strict
```

This makes broken internal links, missing files, and unresolved
anchors fail the build instead of emitting warnings. Add
`--check-external-links` + `pip install 'marimo-book[linkcheck]'` if
you want external URLs validated too — see
[Publishing → Broken-link checking](link_checks.md).
