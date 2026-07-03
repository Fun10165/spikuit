// The only module that touches sigma/graphology. docs/design/graph-viz.md §2.
// A renderer swap (pixi+d3-force fallback, future WebGL alternative) rewrites
// this file only — main.js/ui.js/modes.js/physics.js know nothing about sigma.

(function () {
  "use strict";

  const HIGHLIGHT_FADE_OPACITY = 0.15;

  function withOpacity(hex, opacity) {
    if (opacity >= 1) return hex;
    const m = /^#([0-9a-f]{6})$/i.exec(hex);
    if (!m) return hex;
    const int = parseInt(m[1], 16);
    const r = (int >> 16) & 255, g = (int >> 8) & 255, b = int & 255;
    return "rgba(" + r + "," + g + "," + b + "," + opacity + ")";
  }

  function buildGraph(payload) {
    const graph = new graphology.Graph({ multi: false, type: "directed" });
    for (const n of payload.nodes) {
      graph.addNode(n.id, {
        x: Math.random(),
        y: Math.random(),
        label: n.label,
        baseColor: "#898781",
        baseSize: 6,
        hideLabel: false,
        baseOpacity: 1,
        ring: null,
        payload: n,
      });
    }
    for (const e of payload.edges) {
      const key = e.source + "→" + e.target;
      if (graph.hasNode(e.source) && graph.hasNode(e.target) && !graph.hasEdge(e.source, e.target)) {
        graph.addEdgeWithKey(key, e.source, e.target, {
          baseColor: "#898781",
          baseWidth: 1,
          baseOpacity: 0.5,
          arrow: false,
          payload: e,
        });
      }
    }
    return graph;
  }

  function create(container, payload, ctx) {
    const graph = buildGraph(payload);

    let highlightSet = null; // Set<nodeId> | null — self + neighbors when active
    let visibilitySet = null; // Set<nodeId> | null — ego mode; null = no ego filter
    let hiddenGroups = null; // Set<groupKey> | null
    let hiddenEdgeTypes = null; // Set<string> | null
    let weightMin = 0;

    function nodeVisible(nid, data) {
      if (visibilitySet && !visibilitySet.has(nid)) return false;
      if (hiddenGroups && hiddenGroups.has(String(data.payload.group))) return false;
      return true;
    }

    function edgeVisible(eid, data) {
      if (hiddenEdgeTypes && hiddenEdgeTypes.has(data.payload.type)) return false;
      if (data.payload.weight < weightMin) return false;
      if (visibilitySet) {
        return visibilitySet.has(data.payload.source) && visibilitySet.has(data.payload.target);
      }
      return true;
    }

    const renderer = new Sigma(graph, container, {
      renderEdgeLabels: false,
      defaultEdgeType: "line",
      // Sigma's label layer is a separate canvas from the CSS-themed chrome
      // and defaults to black text — invisible against the dark surface.
      // Follow the active theme's ink token instead.
      labelColor: { color: ctx.tokens.text1 || "#0b0b0b" },
      // CVD relief rule (design doc §4): labels stay visible at default
      // zoom regardless of node pixel size — sigma's own threshold would
      // otherwise hide labels on small (e.g. cold/low-centrality) nodes.
      labelRenderedSizeThreshold: 0,
      edgeProgramClasses: Sigma.rendering && Sigma.rendering.EdgeArrowProgram
        ? { arrow: Sigma.rendering.EdgeArrowProgram }
        : undefined,
      nodeReducer(node, data) {
        const visible = nodeVisible(node, data);
        const res = {
          x: data.x, y: data.y,
          label: data.hideLabel && !(highlightSet && highlightSet.has(node)) ? null : data.label,
          size: data.baseSize,
          color: data.baseColor,
          hidden: !visible,
        };
        if (data.ring) res.zIndex = 2;
        if (highlightSet) {
          if (highlightSet.has(node)) {
            res.forceLabel = true;
          } else {
            res.color = withOpacity(data.baseColor, HIGHLIGHT_FADE_OPACITY);
            res.label = null;
          }
        }
        return res;
      },
      edgeReducer(edge, data) {
        const visible = edgeVisible(edge, data);
        const res = {
          size: data.baseWidth,
          color: data.baseColor,
          hidden: !visible,
          type: data.arrow ? "arrow" : "line",
        };
        if (highlightSet) {
          const inSet = highlightSet.has(data.payload.source) && highlightSet.has(data.payload.target);
          if (!inSet) res.color = withOpacity(data.baseColor, HIGHLIGHT_FADE_OPACITY);
        }
        return res;
      },
    });

    function repaint(modeId) {
      const { nodeAttrs, edgeAttrs } = VizModes.applyMode(modeId, payload, ctx, {});
      graph.forEachNode((nid) => {
        const a = nodeAttrs[nid];
        graph.mergeNodeAttributes(nid, {
          baseColor: a.color, baseSize: a.size, hideLabel: a.hideLabel, baseOpacity: a.opacity, ring: a.ring,
        });
      });
      graph.forEachEdge((eid, data) => {
        const key = data.payload.source + "→" + data.payload.target;
        const a = edgeAttrs[key];
        if (a) {
          graph.mergeEdgeAttributes(eid, {
            baseColor: a.color, baseWidth: a.width, baseOpacity: a.opacity, arrow: a.arrow,
          });
        }
      });
      renderer.refresh();
    }

    function setHighlight(nodeId) {
      if (nodeId == null) {
        highlightSet = null;
      } else {
        highlightSet = new Set([nodeId, ...graph.neighbors(nodeId)]);
      }
      renderer.refresh();
    }

    function setEgo(center, depth) {
      if (center == null) {
        visibilitySet = null;
      } else {
        const seen = new Set([center]);
        let frontier = [center];
        for (let d = 0; d < depth; d++) {
          const next = [];
          for (const nid of frontier) {
            for (const nb of graph.neighbors(nid)) {
              if (!seen.has(nb)) { seen.add(nb); next.push(nb); }
            }
          }
          frontier = next;
        }
        visibilitySet = seen;
      }
      renderer.refresh();
    }

    function setFilters(filters) {
      hiddenGroups = filters.hiddenGroups && filters.hiddenGroups.size ? filters.hiddenGroups : null;
      hiddenEdgeTypes = filters.hiddenEdgeTypes && filters.hiddenEdgeTypes.size ? filters.hiddenEdgeTypes : null;
      weightMin = filters.weightMin || 0;
      renderer.refresh();
    }

    function fit() {
      renderer.getCamera().animatedReset();
    }

    function destroy() {
      renderer.kill();
    }

    return { graph, renderer, repaint, setHighlight, setEgo, setFilters, fit, destroy };
  }

  window.VizRender = { create };
})();
