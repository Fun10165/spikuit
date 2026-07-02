// ForceAtlas2 lifecycle. docs/design/graph-viz.md §6.
//
// Synapse weight drives attraction (edgeWeightInfluence: 1), so screen
// distance approximates semantic distance in every mode — positions are
// mode-independent and filter-independent; no mode or filter ever moves a
// node. Barnes-Hut kicks in above 500 nodes.

(function () {
  "use strict";

  const SETTLE_BASE_MS = 1200;
  const SETTLE_PER_NODE_MS = 3;
  const SETTLE_MAX_MS = 8000;
  const DRAG_REHEAT_MS = 1000;

  function settleDurationFor(nodeCount) {
    return Math.min(SETTLE_MAX_MS, SETTLE_BASE_MS + nodeCount * SETTLE_PER_NODE_MS);
  }

  function prefersReducedMotion() {
    return typeof matchMedia === "function" && matchMedia("(prefers-reduced-motion: reduce)").matches;
  }

  // Runs FA2 for `durationMs`, calling onTick(fractionDone) on each animation
  // frame while it runs, then stops and calls onSettled(). Returns a
  // controller with .fa2 (the supervisor, for drag-reheat / manual restart)
  // and .cancel() to abort early.
  function runToSettle(graph, { durationMs, onTick, onSettled }) {
    const fa2 = new FA2Layout(graph, {
      settings: {
        gravity: 1,
        edgeWeightInfluence: 1,
        barnesHutOptimize: graph.order > 500,
        scalingRatio: 10,
      },
    });

    let cancelled = false;
    const start = performance.now();
    fa2.start();

    function frame() {
      if (cancelled) return;
      const elapsed = performance.now() - start;
      if (onTick) onTick(Math.min(1, elapsed / durationMs));
      if (elapsed >= durationMs) {
        fa2.stop();
        if (onSettled) onSettled();
        return;
      }
      requestAnimationFrame(frame);
    }
    requestAnimationFrame(frame);

    return {
      fa2,
      cancel() {
        cancelled = true;
        if (fa2.isRunning()) fa2.stop();
      },
    };
  }

  // Public entry point. `reduceMotion` skips the visible tick callback and
  // simply reports done once settled — the caller (main.js) is responsible
  // for not painting an in-progress simulation when this is true.
  function initialLayout(graph, { onTick, onSettled, reduceMotion }) {
    const duration = settleDurationFor(graph.order);
    return runToSettle(graph, {
      durationMs: duration,
      onTick: reduceMotion ? null : onTick,
      onSettled,
    });
  }

  // Node drag: re-heat locally for a short window, then stop again. Reuses
  // a fresh FA2Layout each time — the supervisor is single-use per start/stop
  // cycle in practice for this app's needs (short reheat bursts).
  function reheat(graph, onSettled) {
    return runToSettle(graph, { durationMs: DRAG_REHEAT_MS, onTick: null, onSettled });
  }

  window.VizPhysics = { initialLayout, reheat, settleDurationFor, prefersReducedMotion };
})();
