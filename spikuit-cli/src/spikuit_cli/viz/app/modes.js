// ViewSpec registry — the mode system. docs/design/graph-viz.md §5.
//
// A mode changes PAINT ONLY — never positions, physics, filters, or
// selection. Every encoding here is a pure function of payload fields +
// ctx, so this module has zero DOM dependency and is unit-testable under
// plain Node (see tests/test_modes.js).
//
// Phase E1 ships "links" and "strength". "activity" / "memory" / "health"
// land in Phase E2; their ViewSpecs are stubbed with TODO markers kept out
// of MODES so the mode bar only shows what's implemented.

(function (root, factory) {
  if (typeof module === "object" && module.exports) {
    module.exports = factory();
  } else {
    root.VizModes = factory();
  }
})(typeof self !== "undefined" ? self : this, function () {
  "use strict";

  const EDGE_TYPE_ORDER = ["requires", "extends", "contrasts", "relates_to"];

  // -- shared helpers --------------------------------------------------------

  function clamp(v, lo, hi) {
    return Math.max(lo, Math.min(hi, v));
  }

  function normalizeWeight(weight, weightDomain) {
    const [lo, hi] = weightDomain;
    if (hi <= lo) return 0.5;
    return clamp((weight - lo) / (hi - lo), 0, 1);
  }

  // sqrt scale over the payload's own size domain -> [4, 22]px (Links sizing,
  // reused by modes that don't override size).
  function buildSizeScale(nodes) {
    let min = Infinity;
    let max = -Infinity;
    for (const n of nodes) {
      if (n.size_raw < min) min = n.size_raw;
      if (n.size_raw > max) max = n.size_raw;
    }
    if (!isFinite(min) || !isFinite(max)) { min = 0; max = 1; }
    const span = max - min || 1;
    return function sizeScale(raw) {
      const t = clamp((raw - min) / span, 0, 1);
      return 4 + Math.sqrt(t) * 18;
    };
  }

  // 5-bin quantile boundaries over edge weights, for the Strength ramp.
  function buildWeightQuantiles(edges) {
    const weights = edges.map((e) => e.weight).sort((a, b) => a - b);
    if (weights.length === 0) return [0, 0.2, 0.4, 0.6, 0.8, 1];
    function q(p) {
      const idx = clamp(Math.floor(p * (weights.length - 1)), 0, weights.length - 1);
      return weights[idx];
    }
    return [q(0), q(0.2), q(0.4), q(0.6), q(0.8), q(1)];
  }

  function quantileBin(weight, quantiles) {
    // quantiles has 6 boundaries -> 5 bins, indices 0..4.
    for (let i = 1; i < quantiles.length; i++) {
      if (weight <= quantiles[i]) return i - 1;
    }
    return quantiles.length - 2;
  }

  function groupToken(groupSlot, tokens) {
    if (groupSlot === "other" || groupSlot == null) return tokens.sOther;
    return tokens["s" + groupSlot] || tokens.sOther;
  }

  function edgeTypeIndex(type) {
    const i = EDGE_TYPE_ORDER.indexOf(type);
    return i === -1 ? 3 : i; // unknown types render like relates_to
  }

  // Build the ctx object every ViewSpec function receives. Computed once per
  // payload load (not per mode switch — modes never change positions/domains).
  function buildCtx(payload, tokens, theme) {
    return {
      tokens,
      theme,
      weightDomain: payload.meta.weight_domain,
      quantiles: buildWeightQuantiles(payload.edges),
      sizeScale: buildSizeScale(payload.nodes),
    };
  }

  // -- Links mode (default, docs §5.2.1) --------------------------------------

  const EDGE_WIDTH_BASE = [2.5, 2.0, 2.0, 1.2]; // requires, extends, contrasts, relates_to
  const EDGE_OPACITY_BASE = [0.9, 0.8, 0.7, 0.45];
  const EDGE_ARROW = [true, true, false, false];

  const linksMode = {
    id: "links",
    label: "Links",
    hotkey: "1",
    requires: null,
    emphasis: "nodes",
    node: {
      color: (n, ctx) => groupToken(n.group, ctx.tokens),
      size: (n, ctx) => ctx.sizeScale(n.size_raw),
      ring: () => null,
      hideLabel: () => false,
      opacity: () => 1,
    },
    edge: {
      color: (e, ctx) => ctx.tokens.muted,
      width: (e, ctx) => {
        const i = edgeTypeIndex(e.type);
        const w = normalizeWeight(e.weight, ctx.weightDomain);
        return EDGE_WIDTH_BASE[i] * (0.75 + 0.5 * w);
      },
      opacity: (e) => EDGE_OPACITY_BASE[edgeTypeIndex(e.type)],
      arrow: (e) => EDGE_ARROW[edgeTypeIndex(e.type)],
    },
    panelExtras: () => [],
    legend: (ctx, payload) => {
      const groupItems = payload.groups.map((g) => ({
        kind: "swatch",
        color: groupToken(g.slot, ctx.tokens),
        label: g.label + " (" + g.count + ")",
      }));
      return [
        { kind: "section", title: "Groups" },
        ...groupItems,
        { kind: "section", title: "Edge types (width = strength)" },
        {
          kind: "text",
          text: "requires →, extends →, contrasts ┈┈, relates_to ···",
        },
      ];
    },
  };

  // -- Strength mode (docs §5.2.2) ---------------------------------------------

  const strengthMode = {
    id: "strength",
    label: "Strength",
    hotkey: "2",
    requires: null,
    emphasis: "edges",
    node: {
      color: (n, ctx) => ctx.tokens.muted,
      size: (n, ctx) => clamp(ctx.sizeScale(n.size_raw) * 0.45, 3, 10),
      ring: () => null,
      hideLabel: () => true, // except hover/selection — the renderer overrides this
      opacity: () => 0.6,
    },
    edge: {
      color: (e, ctx) => {
        const bin = quantileBin(e.weight, ctx.quantiles);
        return ctx.tokens["ramp" + (bin + 1)];
      },
      width: (e) => 1 + 4 * clamp(e.weight, 0, 1),
      opacity: (e, ctx) => 0.35 + 0.6 * normalizeWeight(e.weight, ctx.weightDomain),
      arrow: () => false,
    },
    panelExtras: (state, payload) => {
      const labelOf = {};
      for (const n of payload.nodes) labelOf[n.id] = n.label;
      // Bidirectional synapse types (contrasts / relates_to) exist as two
      // directed edges in the payload — list each unordered pair once.
      const seenPairs = new Set();
      const top = [];
      for (const e of payload.edges.slice().sort((a, b) => b.weight - a.weight)) {
        const pairKey = [e.source, e.target].sort().join("↔") + "|" + e.type;
        if (seenPairs.has(pairKey)) continue;
        seenPairs.add(pairKey);
        top.push(e);
        if (top.length === 10) break;
      }
      return [
        {
          title: "Strongest synapses",
          items: top.map((e) => ({
            id: e.source + "->" + e.target,
            label: (labelOf[e.source] || e.source) + " — " + (labelOf[e.target] || e.target),
            sublabel: e.type + ", w=" + e.weight.toFixed(2),
            payload: e,
          })),
        },
      ];
    },
    legend: (ctx) => {
      const [q0, q1, q2, q3, q4, q5] = ctx.quantiles;
      const rampItems = [1, 2, 3, 4, 5].map((i) => ({
        kind: "ramp-step",
        color: ctx.tokens["ramp" + i],
      }));
      // Degenerate case: every synapse carries the same weight (common in
      // young brains where nothing has been reinforced yet) — a quintile
      // readout of identical numbers is noise, say the true thing instead.
      if (q5 - q0 < 1e-9) {
        return [
          { kind: "section", title: "Synapse weight" },
          { kind: "text", text: "All synapses currently share the same weight (" + q0.toFixed(2) + ") — reviews that co-fire neurons will differentiate them." },
        ];
      }
      return [
        { kind: "section", title: "Synapse weight (quintile)" },
        { kind: "ramp", steps: rampItems },
        {
          kind: "text",
          text:
            q0.toFixed(2) + " → " + q5.toFixed(2) +
            " (bins at " + [q1, q2, q3, q4].map((v) => v.toFixed(2)).join(", ") + ")",
        },
        { kind: "text", text: "width + opacity both track weight" },
      ];
    },
  };

  const MODES = [linksMode, strengthMode];

  function getMode(id) {
    return MODES.find((m) => m.id === id) || MODES[0];
  }

  // Apply a mode to the full node/edge set -> per-element attribute maps.
  // render.js writes these into graphology attributes; no mode reaches sigma
  // directly.
  function applyMode(modeId, payload, ctx, state) {
    const mode = getMode(modeId);
    const nodeAttrs = {};
    for (const n of payload.nodes) {
      nodeAttrs[n.id] = {
        color: mode.node.color(n, ctx),
        size: mode.node.size(n, ctx),
        ring: mode.node.ring(n, ctx),
        hideLabel: mode.node.hideLabel(n, ctx),
        opacity: mode.node.opacity(n, ctx),
      };
    }
    const edgeAttrs = {};
    for (const e of payload.edges) {
      const key = e.source + "→" + e.target;
      edgeAttrs[key] = {
        color: mode.edge.color(e, ctx),
        width: mode.edge.width(e, ctx),
        opacity: mode.edge.opacity(e, ctx),
        arrow: mode.edge.arrow(e, ctx),
      };
    }
    return { mode, nodeAttrs, edgeAttrs };
  }

  return {
    MODES,
    getMode,
    applyMode,
    buildCtx,
    // exported for tests
    _internal: { normalizeWeight, buildSizeScale, buildWeightQuantiles, quantileBin, groupToken, edgeTypeIndex, clamp },
  };
});
