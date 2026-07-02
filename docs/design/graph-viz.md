# Graph Visualization — design & implementation spec

**Status.** Design draft for review. Supersedes the pyvis-based `spkt visualize`
implementation entirely. Written to be implemented phase-by-phase by an agent;
every module contract, encoding, and acceptance criterion is stated so no design
decisions remain at implementation time. Companion process doc (phases, branch
policy, verification commands): the WP-E plan in the workspace artifacts.

**Goal.** An Obsidian-graph-view-class visualization (WebGL, live force layout,
fluid interaction) with **switchable view modes** that expose what makes Spikuit
graphs unlike a note graph: weighted synapses (STDP), spike activity, memory
state, and structural health. Single self-contained HTML artifact, zero-build.

**Non-goals.** Editing the graph from the view; a served/daemon mode; timeline
replay (deferred, §11); mobile-first layout (container-aware is enough).

---

## 1. Why rebuild

The current `visualize` command (`spikuit-cli/src/spikuit_cli/main.py:1210-1394`)
templates HTML through pyvis and then string-`replace()`s a legend into the
output. Neuron titles are injected into markup unescaped; the palette is 15
unvalidated hex values that cycle; edge hues collide with node-community hues;
node size mixes three unrelated signals; layout is nondeterministic; there are
no tests. None of that is fixable incrementally — the generation pipeline is
replaced wholesale.

## 2. Architecture

```
spikuit-cli/src/spikuit_cli/viz/
├── payload.py     # data contract: substrate → JSON-able dict (pure, tested)
├── app/           # the viz app — vanilla ES modules, no framework, no bundler
│   ├── index.html #   shell: mount points, JSON data island, module inlining order
│   ├── state.js   #   single state store + pub/sub (no external lib)
│   ├── modes.js   #   ViewSpec registry — THE mode system (§5)
│   ├── render.js  #   renderer seam: the only file that imports sigma/graphology
│   ├── physics.js #   ForceAtlas2 config + lifecycle (§6)
│   ├── ui.js      #   mode bar, filter row, detail panel, legend, search (§7)
│   └── theme.css  #   design tokens (§4), container queries
├── build.py       # inliner: app/* + vendored libs + payload → ONE .html
└── vendor/        # sigma.min.js, graphology.min.js, graphology-layout-forceatlas2
                   # (UMD builds, pinned versions, replaces lib/vis-9.1.2 + tom-select)
```

Load order in the generated file: theme.css → vendor UMD bundles → data island →
app modules (concatenated in dependency order by `build.py`) → bootstrap call.
Workers are spawned from inlined source via `Blob` URLs (no external files).

**Invariants**
- `payload.py` knows nothing about rendering; the app knows nothing about the
  substrate. The JSON contract (§3) is the only interface.
- `render.js` is the only module that touches the renderer library. A renderer
  swap (pixi+d3-force fallback, future WebGPU) rewrites this file only.
- All user content (titles, excerpts) crosses into the DOM via `textContent` /
  attribute assignment — never `innerHTML` composition.
- Output is one file, works from `file://`, no network access.

**Renderer**: sigma.js v3 + graphology (WebGL, MIT), ForceAtlas2 in a worker.
Gated by a feasibility spike (plan E1.0): verify UMD-inline + Blob-worker +
hover-fade performance on `file://` before building on it. Fallback if the
spike fails: pixi.js + d3-force with the same module contracts.

## 3. Data contract (payload.py)

```python
async def build_viz_payload(
    circuit, *,
    overlay: str | None = None,        # None | "tutor"
    size_by: str = "centrality",       # centrality | pressure | stability
    spikes_window_days: int = 90,
) -> dict
```

```
meta:   { generated_at, neuron_count, synapse_count, size_by, coloring,
          overlay, component_count, weight_domain: [min, max] }
groups: [ { key, kind: "community"|"domain", label, count, slot: 1..8|"other" } ]
nodes:  [ { id, label, group, size_raw, domain, type, pressure,
            community_id, component_id, excerpt,
            spike_recency,                    # seconds since last spike; null = never
            tutor: null | { stability, difficulty, state, due_in_days } } ]
edges:  [ { source, target, type, weight, co_fires } ]
```

- Strings are data, never markup. `label` = extracted title verbatim; `excerpt`
  = first paragraph ≤200 chars. Adversarial-content tests are mandatory
  (`<script>`, quotes, newlines survive as data).
- `component_id`: connected component of the undirected graph (networkx),
  numbered by size desc — powers the Health mode without app-side graph math.
- `weight_domain`: actual min/max synapse weight — the app scales ramps and the
  threshold slider from this, never from assumed [0,1].
- Substrate-only by default: with `overlay=None` the tutor DB is never opened
  and `tutor` is `null` on every node. `size_by="stability"` requires the
  overlay (validation error otherwise).
- Groups: communities if any exist else domains; top-8 by count desc (tie: key
  asc) take slots 1-8; the rest fold into a single `"other"` group.
- CLI: `spkt visualize --json` prints the payload; `-o/--open/--brain` keep
  their behavior; new `--overlay tutor`, `--size-by`, `--layout` (§6).

## 4. Design tokens (theme.css)

From the validated reference palette (dataviz method). Roles only in app code.

```css
.viz-root{ /* dark = default */
  --surface:#1a1a19; --panel:#242423; --text-1:#ffffff; --text-2:#c3c2b7;
  --muted:#898781; --hairline:#2c2c2a; --ring:rgba(255,255,255,.10);
  --s1:#3987e5; --s2:#199e70; --s3:#c98500; --s4:#008300;
  --s5:#9085e9; --s6:#e66767; --s7:#d55181; --s8:#d95926; --s-other:#898781;
  /* sequential (blue) — prominence-ordered FOR THIS SURFACE, weak→strong */
  --ramp-1:#184f95; --ramp-2:#1c5cab; --ramp-3:#2a78d6;
  --ramp-4:#3987e5; --ramp-5:#6da7ec; --ramp-6:#9ec5f4;
}
@media (prefers-color-scheme: light){ .viz-root{
  --surface:#fcfcfb; --panel:#ffffff; --text-1:#0b0b0b; --text-2:#52514e;
  --muted:#898781; --hairline:#e1e0d9; --ring:rgba(11,11,11,.10);
  --s1:#2a78d6; --s2:#1baf7a; --s3:#eda100; --s4:#008300;
  --s5:#4a3aa7; --s6:#e34948; --s7:#e87ba4; --s8:#eb6834;
  /* light surface: prominence = darker → ramp runs light→dark */
  --ramp-1:#9ec5f4; --ramp-2:#6da7ec; --ramp-3:#3987e5;
  --ramp-4:#2a78d6; --ramp-5:#1c5cab; --ramp-6:#104281;
}}
```

Rules (binding): slot order fixed, never cycled — 9th+ group is `--s-other`;
text always wears text tokens, never series colors; the ramp encodes
**prominence** (weak = recedes toward surface, strong = highest contrast), which
is why its step order differs per surface — dark mode is selected, not
inverted. Any palette change re-runs the dataviz validator; report goes in the
PR. Node labels stay visible at default zoom (CVD relief).

## 5. Mode system — the core

A **mode** answers one question about the same graph. Modes change **paint
only** — never positions, physics, filters, or selection. Switching is an
instant repaint (< 1 frame of work beyond sigma's refresh), so the user's
mental map survives. Buttons in the top bar; hotkeys `1..5`; `m` cycles.

### 5.1 ViewSpec — the declarative contract (modes.js)

```js
// modes.js exports MODES: ViewSpec[] and applyMode(state, graph): PaintPlan
ViewSpec = {
  id, label, hotkey,            // "strength", "Strength", "2"
  requires: null | "tutor",     // unmet → button disabled + tooltip
  emphasis: "nodes" | "edges",  // which layer leads; the other recedes
  node: { color(n,ctx), size(n,ctx), ring(n,ctx) /* null|token */ },
  edge: { color(e,ctx), width(e,ctx), opacity(e,ctx), arrow(e) },
  panelExtras(state) -> Section[],   // e.g. Health category list
  legend(ctx) -> LegendItem[],       // swatches / ramp / width-key / sentence
}
// ctx = { tokens, weightDomain, quantiles, sizeScale, theme }
```

`applyMode` produces per-element attribute maps that `render.js` writes into
graphology attributes and refreshes sigma once. No mode may reach into sigma
directly. Every encoding below is a pure function of payload fields + ctx.

### 5.2 The five modes

**1 · Links** (default) — *what connects to what; where the clusters are.*
- node.color = group slot token; node.size = `sizeScale(size_raw)` =
  sqrt-scaled to [4, 22]px over the payload's size domain.
- edge: neutral (`--muted`); width by type class — requires 2.5 / extends 2.0 /
  contrasts 2.0 / relates_to 1.2 px — each × `(0.75 + 0.5·w̄)` where w̄ =
  weight normalized to `weight_domain`; opacity .9/.8/.7/.45 respectively;
  arrows on requires+extends only.
- legend: group swatches + counts; edge-type width/opacity key.

**2 · Strength** — *where the synapses are strong; what STDP has reinforced.*
The user-named headline mode. Edges are the protagonist; nodes recede.
- node.color = `--muted` at 60% opacity; node.size = clamp to [3, 10]px;
  labels hidden except hover/selection.
- edge.color = `--ramp-N` by weight **quintile** (5 bins over `weight_domain`,
  bins from payload quantiles so a skewed distribution still uses the full
  ramp); edge.width = `1 + 4·w̄`; opacity = `.35 + .6·w̄`; arrows off (hover
  shows direction + type + weight + co_fires).
- The weight-threshold slider (§7) auto-expands in this mode.
- panelExtras: "Strongest synapses" — top-10 list (a — b, w=0.87, requires),
  click → select both endpoints and fit camera.
- legend: 5-step ramp key with the actual bin boundaries + width key sentence.

**3 · Activity** — *what fired recently; where the brain is warm.*
- node.color = ramp by `spike_recency` bucket: ≤24h → ramp-6, ≤3d → ramp-5,
  ≤7d → ramp-4, ≤30d → ramp-3, ≤90d → ramp-2, never/older → `--muted` at 45%
  + hairline ring.
- node.size = Links sizing unchanged; edges = Links style at 55% opacity.
- legend: bucket ramp with labels (today / 3d / 7d / 30d / 90d / dormant).

**4 · Memory** (`requires: "tutor"`) — *what's solid, what's decaying.*
- node.color = ramp by FSRS stability band: <1 → ramp-1, <7 → ramp-2, <21 →
  ramp-3, <90 → ramp-4, ≥90 → ramp-5 (days); uncarded → `--muted` 45%.
- ring = `--text-1` when `due_in_days ≤ 1` (due-now); legend explains the ring
  (never color-alone).
- edges = Links style at 55%; panelExtras: "Due next" top-10 list.

**5 · Health** — *what needs curation.* Category sub-tabs inside the mode
(one category highlighted at a time; the rest of the graph fades to 15%):
- **Islands**: `degree == 0` (degree computed once at load from edges).
- **Cold components**: `component_id` whose members all have
  `spike_recency > 30d` or null, and component size < 5.
- **High pressure**: top decile by `pressure` (skip if all zero).
Highlighted nodes: `--s3` fill + `--ring`; category counts shown on the
sub-tabs; panelExtras lists members (click → select+zoom). Legend = active
category sentence. No status-palette use; one accent + fade carries it.

### 5.3 Color budget rule (binding)

Per mode, color has exactly one job: identity in Links; edge magnitude in
Strength; node magnitude in Activity/Memory; single-accent categorical focus
in Health. Never two color jobs at once — that is what modes are *for*.

## 6. Layout & physics (physics.js)

- ForceAtlas2 (graphology worker build), `edgeWeightInfluence: 1` — synapse
  weight increases attraction, so **screen distance ≈ semantic distance** in
  every mode. Barnes-Hut on above 500 nodes.
- Lifecycle: run-to-settle on load (progress indicator; iteration budget
  scaled by node count, hard cap), then stop. Node drag re-heats for ~1s
  locally. "Re-layout" button restarts. `prefers-reduced-motion` → compute
  settled positions before first paint (no visible simulation).
- **Positions are mode-independent** (§5) and filter-independent: hiding
  elements never re-runs physics (mental-map preservation; matches Obsidian).
- Weight-threshold slider: edges below threshold are hidden (visual) but only
  excluded from physics when the user re-runs layout — the slider itself never
  moves nodes.
- `--layout static` (CLI): positions precomputed in Python
  (`networkx.spring_layout(seed=42, weight="weight")`), embedded in the
  payload, physics disabled → byte-identical output across runs (modulo
  `generated_at`); for sharing and paper figures.

## 7. UI spec (ui.js + theme.css)

```
┌─────────────────────────────────────────────────────────────┐
│ [Links][Strength][Activity][Memory][Health]   [search  /]   │ ← mode bar
│ groups: ●a ●b ●c +2   edges: [req][ext][con][rel]  w≥[──●─] │ ← filter row
│                                              ┌─────────────┐│
│                                              │ detail panel ││
│                 canvas (sigma)               │  or          ││
│                                              │ panelExtras  ││
│                                              └─────────────┘│
│ legend (bottom-left, per-mode)                    [fit][re-layout]
└─────────────────────────────────────────────────────────────┘
```

- **Mode bar**: segmented control; active mode `--text-1` on `--panel`;
  disabled (requires unmet) at 40% + tooltip "generate with --overlay tutor".
- **Filter row**: group chips (toggle; filtering hides, never recolors
  survivors), edge-type chips, node-type dropdown, weight slider (domain from
  `meta.weight_domain`, default = min). Filters are orthogonal to modes.
- **Ego / local-graph mode**: double-click a node (or panel button) → show only
  the N-hop neighborhood, depth stepper 1-3, positions unchanged, camera fits;
  "back to full graph" chip appears in the filter row. Orthogonal to modes.
- **Selection**: click = select + neighbors full / rest fade 15%; `Esc` clears.
  Hover = temporary same effect (cheap: sigma reducers).
- **Detail panel**: title (`textContent`), group/domain/type chips, pressure,
  synapse list sorted by weight (type + weight, click → jump), excerpt, tutor
  block when present, copy-id. Collapses to a bottom sheet when the **container**
  is narrower than ~640px (`@container` query; device media queries are
  prohibited except `prefers-color-scheme` / `prefers-reduced-motion`).
- **Tooltips**: HTML overlays positioned from sigma events (never `title=`),
  `--panel` surface + `--ring` border.
- Keyboard: `1..5` modes, `m` cycle, `/` search, `f` fit, `d` toggle panel,
  `Esc` clear. All controls reachable by tab; buttons are real `<button>`s.

## 8. State (state.js)

```js
state = {
  mode: "links",
  selection: null,                   // nodeId
  ego: null,                         // { center, depth }
  filters: { groups:Set, edgeTypes:Set, nodeTypes:Set, weightMin:number },
  theme: matchMedia-derived,
}
```
Plain object + `subscribe(fn)` / `update(patch)`; every UI element renders from
state; `render.js` consumes state diffs (mode → repaint, filters/ego →
visibility pass, selection → reducer pass). No framework, no external state lib.

## 9. Testing

- **payload**: unit tests as in §3 (counts, slotting, Other-fold, tutor-less,
  adversarial titles, `--json` round-trip, component numbering, weight_domain).
- **build.py**: data island extract → `json.loads` OK; `</script>` escaping;
  all vendor bundles + modules present exactly once; both theme token sets.
- **modes.js is pure** → unit-testable without a browser: feed a fixture
  payload through each ViewSpec, assert encodings (e.g. weight 0.9 lands in
  ramp-5 quintile; never-spiked node gets muted+ring; Memory disabled without
  tutor). Run under `node` in CI (modules are browser-free by design).
- **Smoke**: generate against a fixture brain; assert no adversarial string
  outside the JSON island.
- **Manual render-and-look** (mandatory, per phase): real daily brain + 1k
  synthetic; walk all 5 modes, resize pane, both themes; screenshots in PR.

## 10. Performance targets

50-node daily brain: instant. 1k synthetic: first paint < 1.5s, settle < 5s,
pan/zoom 60fps. 5k synthetic: first paint < 4s, interaction ≥ 30fps, labels
LOD-culled (top-K by size + zoom threshold when > 300 nodes; hover tooltips
throttled > 2000). Benchmark numbers recorded in the E3 PR.

## 11. Deferred (recorded, not designed)

Spike-history time scrub / replay animation (needs per-node spike series in the
payload; design after modes prove daily-useful). Edge bundling. WebGPU. Served
mode with lazy content loading. Paper-figure export presets beyond
`--layout static`.

## 12. Review round

No open blocking questions — encodings, module contracts, and UI are fully
specified above; recommendations are baked in (UI labels in English; five modes;
threshold slider defaults to min = everything visible). Veto or amend any
numbered decision; silence = proceed as written.
