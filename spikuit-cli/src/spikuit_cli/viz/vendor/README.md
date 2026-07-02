# Vendored viz libraries

Pinned browser-ready builds. `spkt visualize`'s output HTML inlines these —
no CDN, no network access, works from `file://`.

| File | Package | Version | Source |
|---|---|---|---|
| `sigma.min.js` | `sigma` | 3.0.3 | `dist/sigma.min.js` — already a self-contained UMD build (exposes global `Sigma`). Fetched as-is. |
| `graphology.umd.min.js` | `graphology` | 0.26.0 | `dist/graphology.umd.min.js` — already a self-contained UMD build (exposes global `graphology`). Fetched as-is. |
| `graphology-layout-forceatlas2.bundle.js` | `graphology-layout-forceatlas2` | 0.10.1 | **Not a UMD build upstream** — the package ships raw CommonJS source only (`require`/`module.exports`, no `dist/`). Bundled once with esbuild (see below) into a self-contained global `FA2Layout`. |

## Why FA2 needs a build step (and why that's fine)

Confirmed during the E1.0 feasibility spike: `graphology-layout-forceatlas2`'s
worker supervisor (`worker.js`) already uses the exact Blob-URL pattern this
project's design calls for —
[`helpers.createWorker`](https://unpkg.com/browse/graphology-layout-forceatlas2@0.10.1/helpers.js)
does `new Worker(URL.createObjectURL(new Blob([fn.toString()...])))` internally.
It's just distributed as unbundled CJS source, meant to be consumed through a
bundler in a normal npm project — there's no `dist/` UMD build on npm/unpkg to
fetch directly.

This only affects how the vendored file gets **produced** (once, by whoever
updates it) — the **shipped artifact** (`spkt visualize`'s output HTML) stays
zero-build: it just inlines the resulting static `.js` file like the other two.

### Regenerating `graphology-layout-forceatlas2.bundle.js`

```sh
mkdir -p /tmp/fa2-bundle && cd /tmp/fa2-bundle
npm init -y >/dev/null
npm install graphology-layout-forceatlas2@0.10.1
cat > entry.js <<'EOF'
const FA2Layout = require('graphology-layout-forceatlas2/worker');
window.FA2Layout = FA2Layout;
EOF
npx esbuild entry.js --bundle --platform=browser --format=iife \
    --outfile=graphology-layout-forceatlas2.bundle.js
```

Verify the output has zero `require(` calls before replacing the vendored copy
(`grep -c 'require(' graphology-layout-forceatlas2.bundle.js` → `0`).

## Usage in generated pages

```html
<script src="graphology.umd.min.js"></script>   <!-- global: graphology -->
<script src="sigma.min.js"></script>             <!-- global: Sigma -->
<script src="graphology-layout-forceatlas2.bundle.js"></script>  <!-- global: FA2Layout -->
<script>
  const graph = new graphology.Graph();
  // ...
  const renderer = new Sigma(graph, container);
  const fa2 = new FA2Layout(graph, { settings: { gravity: 1 } });
  fa2.start();
</script>
```
