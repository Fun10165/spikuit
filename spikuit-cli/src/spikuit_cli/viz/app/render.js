// The only module that touches sigma/graphology. docs/design/graph-viz.md §2.
// A renderer swap (pixi+d3-force fallback, future WebGL alternative) rewrites
// this file only — main.js/ui.js/modes.js/physics.js know nothing about sigma.

(function () {
  "use strict";

  // Faded elements use a SOLID pre-blended color, never an alpha rgba():
  // sigma's WebGL node program packs the color+alpha per vertex and blends
  // against whatever canvas layers sit below, which produced visibly wrong
  // tints (verified: nodes rendered lighter, not dimmer, on the dark
  // surface). Solid blends toward the surface color are the pattern
  // sigma's own hover-highlight examples use, and they render exactly as
  // computed on every layer.
  function blendToward(hex, surfaceHex, t) {
    const parse = (h) => {
      const m = /^#([0-9a-f]{6})$/i.exec(h);
      if (!m) return null;
      const int = parseInt(m[1], 16);
      return [(int >> 16) & 255, (int >> 8) & 255, int & 255];
    };
    const a = parse(hex);
    const b = parse(surfaceHex);
    if (!a || !b) return hex;
    const mix = a.map((v, i) => Math.round(v + (b[i] - v) * t));
    return "#" + mix.map((v) => v.toString(16).padStart(2, "0")).join("");
  }

  // Theme-aware hover renderer. sigma's default (drawDiscNodeHover)
  // hardcodes a WHITE label-box background and then draws the label in
  // settings.labelColor — which this app sets to the theme ink (white in
  // dark mode), producing an unreadable white-on-white box. Draw the box
  // on the panel surface with a hairline border and ink text instead.
  function makeNodeHoverDrawer(tokens) {
    return function drawNodeHover(context, data, settings) {
      const size = settings.labelSize;
      context.font = settings.labelWeight + " " + size + "px " + settings.labelFont;

      if (typeof data.label === "string" && data.label) {
        const PAD = 5;
        const textWidth = context.measureText(data.label).width;
        const boxW = Math.round(textWidth + PAD * 2);
        const boxH = Math.round(size + PAD * 2);
        // Flip the box to the node's left when it would run off the right
        // edge of the *visible* area: either the viewport edge (canvas.width
        // is device px; convert to the CSS px space data.x/y live in) or,
        // when the detail panel is open, the panel's left edge — the panel
        // overlays the canvas and would otherwise hide the label.
        let rightBound = context.canvas.width / (window.devicePixelRatio || 1);
        const panel = document.querySelector('.viz-panel[data-open="true"]');
        if (panel) {
          const panelLeft = panel.getBoundingClientRect().left;
          if (panelLeft < rightBound) rightBound = panelLeft;
        }
        let boxX = Math.round(data.x + data.size + 4);
        if (boxX + boxW > rightBound - 4) {
          boxX = Math.round(data.x - data.size - 4 - boxW);
        }
        const boxY = Math.round(data.y - boxH / 2);

        context.beginPath();
        if (context.roundRect) context.roundRect(boxX, boxY, boxW, boxH, 5);
        else context.rect(boxX, boxY, boxW, boxH);
        context.shadowOffsetX = 0;
        context.shadowOffsetY = 2;
        context.shadowBlur = 8;
        context.shadowColor = "rgba(0,0,0,0.45)";
        context.fillStyle = tokens.panel;
        context.fill();
        context.shadowOffsetY = 0;
        context.shadowBlur = 0;
        context.strokeStyle = tokens.hairline;
        context.lineWidth = 1;
        context.stroke();

        context.fillStyle = tokens.text1;
        context.fillText(data.label, boxX + PAD, data.y + size / 3);
      }

      // Halo ring on the node itself so the hover target reads even when
      // the label box sits to one side.
      context.beginPath();
      context.arc(data.x, data.y, data.size + 2, 0, Math.PI * 2);
      context.strokeStyle = tokens.text1;
      context.lineWidth = 1.5;
      context.stroke();
    };
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
    let highlightCenter = null; // the node the highlight was requested for
    let visibilitySet = null; // Set<nodeId> | null — ego mode; null = no ego filter
    let hiddenGroups = null; // Set<groupKey> | null
    let hiddenEdgeTypes = null; // Set<string> | null
    let weightMin = 0;
    let preEgoCamera = null; // camera state to restore when leaving ego mode
    const drawnLabelRects = []; // per-frame label rects, for collision culling

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
      // CVD relief rule (design doc §4): labels must stay ACCESSIBLE, which
      // "always render every node's label regardless of density" doesn't
      // actually serve — sigma's default grid-based culling is keyed on
      // node position, not text width, so long labels overlap badly at
      // real-brain node counts (~200+) even when nodes themselves aren't
      // crowded. Every node's label is still guaranteed reachable via
      // hover/selection (forceLabel below) — the relief is "never
      // permanently hidden", not "always all rendered at once".
      // labelRenderedSizeThreshold left at sigma's default (6).
      // The grid dedupes labels per CELL, keyed on node position — it knows
      // nothing about rendered text width, so adjacent cells can both pick
      // long labels that collide. Cell size is therefore set near this
      // brain's typical rendered label width (long bilingual titles run
      // ~300px), trading label quantity for guaranteed legibility; hover,
      // selection, and search all surface the rest on demand.
      labelGridCellSize: 300,
      labelDensity: 0.5,
      defaultDrawNodeHover: makeNodeHoverDrawer(ctx.tokens),
      // Custom label drawer, three jobs:
      // 1. Skip highlighted nodes — the hovers layer draws their boxed
      //    label (see makeNodeHoverDrawer); without this the label grid can
      //    also pick the same node and double-draw it.
      // 2. Ink token for the text (sigma's default is black-on-anything).
      // 3. Text-width collision culling: the label grid dedupes by node
      //    POSITION per cell and knows nothing about rendered text width,
      //    so two adjacent nodes (e.g. a connected pair sitting tangent)
      //    can both win labels whose long text overlaps. Track the rects
      //    drawn this frame and skip any label that would intersect one —
      //    grid order is deterministic, so which of the two survives is
      //    stable frame to frame.
      defaultDrawNodeLabel(context, data, settings) {
        if (data.highlighted || !data.label) return;
        context.font = settings.labelWeight + " " + settings.labelSize + "px " + settings.labelFont;
        const w = context.measureText(data.label).width;
        const rect = {
          x: data.x + data.size + 3,
          y: data.y - settings.labelSize / 2 - 1,
          w: w,
          h: settings.labelSize + 2,
        };
        for (const r of drawnLabelRects) {
          if (rect.x < r.x + r.w && rect.x + rect.w > r.x && rect.y < r.y + r.h && rect.y + rect.h > r.y) {
            return; // would overlap an already-drawn label — skip
          }
        }
        drawnLabelRects.push(rect);
        context.fillStyle = ctx.tokens.text1;
        context.fillText(data.label, rect.x, data.y + settings.labelSize / 3);
      },
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
            // Label only the center — via sigma's highlighted path, which
            // routes through our theme-aware hover drawer (boxed label,
            // viewport/panel-edge flipping) instead of a bare text label.
            // Neighbors keep full color but no canvas label: strongly-
            // weighted neighbors sit nearly on top of each other in this
            // layout (verified on the real brain), so any second label in
            // the neighborhood garbles with the center's — and
            // identification is already covered by hovering the neighbor
            // and by the detail panel's synapse list.
            if (node === highlightCenter) {
              res.highlighted = true;
            } else {
              res.label = null;
            }
            res.zIndex = 3;
          } else {
            // Solid blend, not alpha — see blendToward's comment.
            res.color = blendToward(data.baseColor, ctx.tokens.surface, 0.82);
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
          if (!inSet) res.color = blendToward(data.baseColor, ctx.tokens.surface, 0.85);
        }
        return res;
      },
    });

    // Reset the label-collision ledger at the start of every render frame
    // (sigma clears the labels canvas then re-draws all grid-picked labels).
    renderer.on("beforeRender", () => {
      drawnLabelRects.length = 0;
    });

    function repaint(modeId) {
      const { nodeAttrs, edgeAttrs } = VizModes.applyMode(modeId, payload, ctx, {});
      graph.forEachNode((nid) => {
        const a = nodeAttrs[nid];
        graph.mergeNodeAttributes(nid, {
          baseColor: a.color, baseSize: a.size, hideLabel: a.hideLabel, baseOpacity: a.opacity, ring: a.ring,
          // `size` is what FA2's adjustSizes reads for overlap-avoiding
          // repulsion; sigma's own display size still comes from the
          // reducer (baseSize), so this is layout-only.
          size: a.size,
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
      highlightCenter = nodeId == null ? null : nodeId;
      if (nodeId == null) {
        highlightSet = null;
      } else {
        highlightSet = new Set([nodeId, ...graph.neighbors(nodeId)]);
      }
      renderer.refresh();
    }

    function setEgo(center, depth) {
      const camera = renderer.getCamera();
      if (center == null) {
        visibilitySet = null;
        renderer.refresh();
        if (preEgoCamera) {
          camera.animate(preEgoCamera, { duration: 300 });
          preEgoCamera = null;
        }
        return;
      }
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
      renderer.refresh();

      // Fit the camera to the ego set. Strongly-weighted neighbors sit
      // almost on top of each other in the layout, so without zooming in
      // the ego view can look like a single node (verified on the real
      // brain). Uses sigma's framed (normalized) coordinates, which are
      // what camera x/y/ratio are expressed in.
      if (!preEgoCamera) preEgoCamera = camera.getState();
      let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity;
      seen.forEach((nid) => {
        const dd = renderer.getNodeDisplayData(nid);
        if (!dd) return;
        if (dd.x < minX) minX = dd.x;
        if (dd.x > maxX) maxX = dd.x;
        if (dd.y < minY) minY = dd.y;
        if (dd.y > maxY) maxY = dd.y;
      });
      if (isFinite(minX)) {
        const extent = Math.max(maxX - minX, maxY - minY);
        camera.animate(
          {
            x: (minX + maxX) / 2,
            y: (minY + maxY) / 2,
            // ratio < 1 zooms in; keep a floor so a co-located pair doesn't
            // zoom to sub-pixel scales, and padding so nodes aren't at the
            // viewport edge.
            ratio: Math.max(extent * 1.6, 0.08),
          },
          { duration: 300 }
        );
      }
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
