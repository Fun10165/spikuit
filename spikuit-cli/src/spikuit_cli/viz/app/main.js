// Bootstrap. docs/design/graph-viz.md §2/§6/§7.

(function () {
  "use strict";

  const TOKEN_VARS = {
    s1: "--s1", s2: "--s2", s3: "--s3", s4: "--s4",
    s5: "--s5", s6: "--s6", s7: "--s7", s8: "--s8",
    sOther: "--s-other", muted: "--muted",
    ramp1: "--ramp-1", ramp2: "--ramp-2", ramp3: "--ramp-3",
    ramp4: "--ramp-4", ramp5: "--ramp-5", ramp6: "--ramp-6",
  };

  function readTokens(rootEl) {
    const style = getComputedStyle(rootEl);
    const tokens = {};
    for (const key in TOKEN_VARS) {
      tokens[key] = style.getPropertyValue(TOKEN_VARS[key]).trim();
    }
    return tokens;
  }

  function wireDrag(render) {
    const captor = render.renderer.getMouseCaptor();
    let dragging = null;

    render.renderer.on("downNode", ({ node }) => {
      dragging = node;
      render.renderer.getCamera().disable();
    });

    captor.on("mousemovebody", (coords) => {
      if (!dragging) return;
      const pos = render.renderer.viewportToGraph(coords);
      render.graph.setNodeAttribute(dragging, "x", pos.x);
      render.graph.setNodeAttribute(dragging, "y", pos.y);
      coords.preventSigmaDefault();
      render.renderer.refresh();
    });

    function release() {
      if (!dragging) return;
      dragging = null;
      render.renderer.getCamera().enable();
      window.dispatchEvent(new CustomEvent("viz:reheat"));
    }
    captor.on("mouseup", release);
    captor.on("mouseleave", release);
  }

  function main() {
    const rootEl = document.querySelector(".viz-root");
    const dataEl = document.getElementById("graph-data");
    const payload = JSON.parse(dataEl.textContent);

    const canvasEl = document.getElementById("viz-canvas");
    const progressEl = document.getElementById("viz-progress");
    const tokens = readTokens(rootEl);

    const state = VizState.createState({});
    const ctx = VizModes.buildCtx(payload, tokens, state.get().theme);
    const render = VizRender.create(canvasEl, payload, ctx);
    render.repaint(state.get().mode);

    VizUI.mount(rootEl, {
      state, render, payload, ctx, tokens,
      overlay: payload.meta.overlay,
    });

    // Hover = temporary ego-highlight; click = persistent selection.
    let hovering = null;
    render.renderer.on("enterNode", ({ node }) => {
      hovering = node;
      render.setHighlight(node);
    });
    render.renderer.on("leaveNode", () => {
      hovering = null;
      render.setHighlight(state.get().selection);
    });
    render.renderer.on("clickNode", ({ node }) => {
      state.update({ selection: node });
    });
    render.renderer.on("clickStage", () => {
      state.update({ selection: null, ego: null });
    });
    render.renderer.on("doubleClickNode", (payload_) => {
      payload_.event.preventSigmaDefault();
      const current = state.get().ego;
      const depth = current && current.center === payload_.node ? Math.min(3, current.depth + 1) : 1;
      state.update({ ego: { center: payload_.node, depth } });
    });

    state.subscribe((s, prev) => {
      if (s.selection !== prev.selection && !hovering) {
        // selection change while not hovering already handled by ui.js's
        // own subscriber calling render.setHighlight; nothing extra here.
      }
    });

    wireDrag(render);

    function runLayout(reduceMotion) {
      if (reduceMotion) canvasEl.style.visibility = "hidden";
      progressEl.style.display = "block";
      VizPhysics.initialLayout(render.graph, {
        reduceMotion,
        onTick(frac) {
          progressEl.textContent = "Laying out… " + Math.round(frac * 100) + "%";
        },
        onSettled() {
          progressEl.style.display = "none";
          canvasEl.style.visibility = "visible";
          render.renderer.refresh();
          window.__vizSettled = true;
        },
      });
    }

    window.addEventListener("viz:relayout", () => runLayout(false));
    window.addEventListener("viz:reheat", () => {
      VizPhysics.reheat(render.graph, () => render.renderer.refresh());
    });

    runLayout(VizPhysics.prefersReducedMotion());

    window.__viz = { state, render, payload }; // for tests / debugging
    window.__vizReady = true;
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", main);
  } else {
    main();
  }
})();
