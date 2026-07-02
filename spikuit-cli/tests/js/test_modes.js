// Pure unit tests for viz/app/modes.js — run under plain Node, no browser.
// docs/design/graph-viz.md §9: "modes.js is pure -> unit-testable without a
// browser." Run with: node spikuit-cli/tests/js/test_modes.js

const assert = require("assert");
const path = require("path");
const VizModes = require(path.join(__dirname, "..", "..", "src", "spikuit_cli", "viz", "app", "modes.js"));

const TOKENS = {
  s1: "#3987e5", s2: "#199e70", s3: "#c98500", s4: "#008300",
  s5: "#9085e9", s6: "#e66767", s7: "#d55181", s8: "#d95926",
  sOther: "#898781", muted: "#898781",
  ramp1: "#184f95", ramp2: "#1c5cab", ramp3: "#2a78d6",
  ramp4: "#3987e5", ramp5: "#6da7ec", ramp6: "#9ec5f4",
};

function fixturePayload() {
  return {
    meta: { weight_domain: [0.1, 0.9] },
    groups: [
      { key: "math", kind: "domain", label: "math", count: 3, slot: 1 },
      { key: "other", kind: "domain", label: "Other", count: 1, slot: "other" },
    ],
    nodes: [
      { id: "n1", group: 1, size_raw: 0.0 },
      { id: "n2", group: 1, size_raw: 0.5 },
      { id: "n3", group: 1, size_raw: 1.0 },
      { id: "n4", group: "other", size_raw: 0.2 },
    ],
    edges: [
      { source: "n1", target: "n2", type: "requires", weight: 0.1 },
      { source: "n2", target: "n3", type: "extends", weight: 0.3 },
      { source: "n3", target: "n4", type: "contrasts", weight: 0.5 },
      { source: "n4", target: "n1", type: "relates_to", weight: 0.7 },
      { source: "n1", target: "n3", type: "requires", weight: 0.9 },
    ],
  };
}

let passed = 0;
function test(name, fn) {
  try {
    fn();
    passed++;
    console.log("  ok - " + name);
  } catch (err) {
    console.error("  FAIL - " + name);
    console.error("    " + err.message);
    process.exitCode = 1;
  }
}

console.log("test_modes.js");

// -- registry shape -----------------------------------------------------------

test("MODES exposes exactly links and strength in E1", () => {
  const ids = VizModes.MODES.map((m) => m.id);
  assert.deepStrictEqual(ids, ["links", "strength"]);
});

test("getMode falls back to links for an unknown id", () => {
  assert.strictEqual(VizModes.getMode("bogus").id, "links");
});

// -- shared helpers -------------------------------------------------------------

test("normalizeWeight clamps to [0,1] and handles a degenerate domain", () => {
  const { normalizeWeight } = VizModes._internal;
  assert.strictEqual(normalizeWeight(0.1, [0.1, 0.9]), 0);
  assert.strictEqual(normalizeWeight(0.9, [0.1, 0.9]), 1);
  assert.strictEqual(normalizeWeight(0.5, [0.1, 0.9]), 0.5);
  assert.strictEqual(normalizeWeight(5, [1, 1]), 0.5); // lo == hi -> neutral
});

test("buildSizeScale maps the min/max of size_raw to a sqrt curve in [4,22]", () => {
  const { buildSizeScale } = VizModes._internal;
  const scale = buildSizeScale([{ size_raw: 0 }, { size_raw: 10 }]);
  assert.strictEqual(scale(0), 4);
  assert.strictEqual(scale(10), 22);
  const mid = scale(5);
  assert.ok(mid > 4 && mid < 22);
});

test("groupToken maps slot 1..8 to s1..s8 and anything else to sOther", () => {
  const { groupToken } = VizModes._internal;
  assert.strictEqual(groupToken(1, TOKENS), TOKENS.s1);
  assert.strictEqual(groupToken(8, TOKENS), TOKENS.s8);
  assert.strictEqual(groupToken("other", TOKENS), TOKENS.sOther);
  assert.strictEqual(groupToken(null, TOKENS), TOKENS.sOther);
  assert.strictEqual(groupToken(99, TOKENS), TOKENS.sOther); // never a 9th real slot
});

test("buildWeightQuantiles + quantileBin: max weight lands in the top bin", () => {
  const { buildWeightQuantiles, quantileBin } = VizModes._internal;
  const payload = fixturePayload();
  const q = buildWeightQuantiles(payload.edges);
  assert.strictEqual(q.length, 6);
  assert.strictEqual(quantileBin(0.9, q), 4); // the weight-0.9 edge -> 5th bin (index 4)
  assert.strictEqual(quantileBin(q[0], q), 0); // the minimum weight -> 1st bin
});

// -- Links mode -----------------------------------------------------------------

test("Links: node color follows group slot, never cycles past 8", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const { nodeAttrs } = VizModes.applyMode("links", payload, ctx, {});
  assert.strictEqual(nodeAttrs.n1.color, TOKENS.s1);
  assert.strictEqual(nodeAttrs.n4.color, TOKENS.sOther); // folded "other" group
});

test("Links: edge width scales by type-class base and weight, requires > relates_to", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const { edgeAttrs } = VizModes.applyMode("links", payload, ctx, {});
  const requiresEdge = edgeAttrs["n1→n2"]; // type=requires, weight=0.1 (lowest)
  const relatesEdge = edgeAttrs["n4→n1"]; // type=relates_to, weight=0.7
  assert.ok(requiresEdge.width > relatesEdge.width, "requires base width (2.5) should beat a higher-weight relates_to (base 1.2)");
});

test("Links: arrows only on requires/extends (color follows entity, not edge type via hue)", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const { edgeAttrs } = VizModes.applyMode("links", payload, ctx, {});
  assert.strictEqual(edgeAttrs["n1→n2"].arrow, true); // requires
  assert.strictEqual(edgeAttrs["n2→n3"].arrow, true); // extends
  assert.strictEqual(edgeAttrs["n3→n4"].arrow, false); // contrasts
  assert.strictEqual(edgeAttrs["n4→n1"].arrow, false); // relates_to
  // Edge hue is uniformly muted in Links — never impersonates a node's
  // categorical color (the bug the old pyvis path had).
  Object.values(edgeAttrs).forEach((a) => assert.strictEqual(a.color, TOKENS.muted));
});

// -- Strength mode ----------------------------------------------------------------

test("Strength: nodes recede (muted, small, hidden labels) — edges are the protagonist", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const { nodeAttrs } = VizModes.applyMode("strength", payload, ctx, {});
  assert.strictEqual(nodeAttrs.n1.color, TOKENS.muted);
  assert.ok(nodeAttrs.n1.size <= 10);
  assert.strictEqual(nodeAttrs.n1.hideLabel, true);
  assert.strictEqual(nodeAttrs.n1.opacity, 0.6);
});

test("Strength: edge color follows the weight quintile ramp, not node identity", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const { edgeAttrs } = VizModes.applyMode("strength", payload, ctx, {});
  const weak = edgeAttrs["n1→n2"]; // weight 0.1, the minimum
  const strong = edgeAttrs["n1→n3"]; // weight 0.9, the maximum
  assert.strictEqual(weak.color, TOKENS.ramp1);
  assert.strictEqual(strong.color, TOKENS.ramp5);
  assert.ok(strong.width > weak.width);
  assert.ok(strong.opacity > weak.opacity);
});

test("Strength: no mode ever assigns two color jobs at once (color budget rule)", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const { nodeAttrs, edgeAttrs } = VizModes.applyMode("strength", payload, ctx, {});
  // Every node gets the SAME muted color in Strength — color carries no
  // per-node identity information here, only edges do.
  const nodeColors = new Set(Object.values(nodeAttrs).map((a) => a.color));
  assert.strictEqual(nodeColors.size, 1);
});

test("Strength: panelExtras surfaces the top-10 synapses by weight, strongest first", () => {
  const payload = fixturePayload();
  const mode = VizModes.getMode("strength");
  const sections = mode.panelExtras({}, payload);
  assert.strictEqual(sections[0].title, "Strongest synapses");
  assert.strictEqual(sections[0].items[0].sublabel, "requires, w=0.90");
});

test("Strength: legend reports the actual quantile bin boundaries, not assumed [0,1]", () => {
  const payload = fixturePayload();
  const ctx = VizModes.buildCtx(payload, TOKENS, "dark");
  const mode = VizModes.getMode("strength");
  const legend = mode.legend(ctx, payload);
  const text = legend.find((l) => l.kind === "text" && l.text.includes("→"));
  assert.ok(text.text.startsWith("0.10"), "legend should reflect the fixture's actual min weight (0.1), not a hardcoded 0.00");
});

console.log(passed + " passed");
if (process.exitCode) {
  console.error("SOME TESTS FAILED");
} else {
  console.log("ALL PASSED");
}
