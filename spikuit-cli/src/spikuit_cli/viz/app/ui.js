// Mode bar, filter row, detail panel, legend, search. docs/design/graph-viz.md §7.
// Every element renders from `state`; render.js is called for the effects
// (repaint on mode change, setHighlight on hover/select, setEgo, setFilters).

(function () {
  "use strict";

  const EDGE_TYPE_LABELS = { requires: "requires", extends: "extends", contrasts: "contrasts", relates_to: "relates_to" };

  function el(tag, attrs, children) {
    const e = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === "text") e.textContent = attrs[k];
        else if (k.startsWith("on")) e.addEventListener(k.slice(2).toLowerCase(), attrs[k]);
        else e.setAttribute(k, attrs[k]);
      }
    }
    (children || []).forEach((c) => c && e.appendChild(c));
    return e;
  }

  function groupToken(slot, tokens) {
    if (slot === "other" || slot == null) return tokens.sOther;
    return tokens["s" + slot] || tokens.sOther;
  }

  function mount(root, { state, render, payload, ctx, tokens, overlay }) {
    // -- top bar: mode bar + search -----------------------------------------

    const modeBar = el("div", { class: "viz-modebar" });
    VizModes.MODES.forEach((mode) => {
      const disabled = mode.requires && mode.requires !== overlay;
      const btn = el("button", {
        class: "viz-mode-btn",
        "aria-pressed": String(state.get().mode === mode.id),
        title: disabled ? "generate with --overlay " + mode.requires : mode.label + " (" + mode.hotkey + ")",
        text: mode.label,
        onClick: () => { if (!disabled) state.update({ mode: mode.id }); },
      });
      if (disabled) btn.disabled = true;
      modeBar.appendChild(btn);
    });

    const searchWrap = el("div", { style: "position:relative" });
    const searchInput = el("input", { class: "viz-search", type: "text", placeholder: "Search (/)" });
    const searchResults = el("div", { class: "viz-search-results" });
    searchResults.style.display = "none";
    searchWrap.appendChild(searchInput);
    searchWrap.appendChild(searchResults);

    searchInput.addEventListener("input", () => {
      const q = searchInput.value.trim().toLowerCase();
      searchResults.innerHTML = "";
      if (!q) { searchResults.style.display = "none"; return; }
      const matches = payload.nodes.filter((n) => n.label.toLowerCase().includes(q)).slice(0, 20);
      if (!matches.length) { searchResults.style.display = "none"; return; }
      matches.forEach((n) => {
        const row = el("div", { class: "viz-search-result", text: n.label, onClick: () => selectNode(n.id) });
        searchResults.appendChild(row);
      });
      searchResults.style.display = "block";
    });

    const topRow = el("div", { class: "viz-row" }, [modeBar, searchWrap]);

    // -- filter row -----------------------------------------------------------

    const hiddenGroups = new Set();
    const hiddenEdgeTypes = new Set();
    let weightMin = payload.meta.weight_domain[0];

    function pushFilters() {
      render.setFilters({ hiddenGroups, hiddenEdgeTypes, weightMin });
    }

    const groupChips = payload.groups.map((g) => {
      const chip = el("div", {
        class: "viz-chip", "data-active": "true",
        onClick: () => {
          if (hiddenGroups.has(g.key)) hiddenGroups.delete(g.key); else hiddenGroups.add(g.key);
          chip.setAttribute("data-active", String(!hiddenGroups.has(g.key)));
          pushFilters();
        },
      }, [
        el("span", { class: "viz-chip-swatch", style: "background:" + groupToken(g.slot, tokens) }),
        document.createTextNode(g.label),
      ]);
      return chip;
    });

    const edgeChips = Object.keys(EDGE_TYPE_LABELS).map((type) => {
      const chip = el("div", {
        class: "viz-chip", "data-active": "true",
        text: EDGE_TYPE_LABELS[type],
        onClick: () => {
          if (hiddenEdgeTypes.has(type)) hiddenEdgeTypes.delete(type); else hiddenEdgeTypes.add(type);
          chip.setAttribute("data-active", String(!hiddenEdgeTypes.has(type)));
          pushFilters();
        },
      });
      return chip;
    });

    const [wLo, wHi] = payload.meta.weight_domain;
    const weightSlider = el("input", {
      type: "range", min: String(wLo), max: String(wHi), step: String((wHi - wLo) / 100 || 0.01), value: String(wLo),
    });
    weightSlider.addEventListener("input", () => {
      weightMin = parseFloat(weightSlider.value);
      pushFilters();
    });
    const weightWrap = el("div", { class: "viz-slider-wrap" }, [
      document.createTextNode("weight ≥"),
      weightSlider,
    ]);

    const filterRow = el("div", { class: "viz-row" }, [...groupChips, ...edgeChips, weightWrap]);
    const topbar = el("div", { class: "viz-topbar" }, [topRow, filterRow]);

    // -- legend --------------------------------------------------------------

    const legendEl = el("div", { class: "viz-legend" });

    function renderLegend() {
      const mode = VizModes.getMode(state.get().mode);
      const items = mode.legend(ctx, payload);
      legendEl.innerHTML = "";
      legendEl.appendChild(el("div", { class: "viz-legend-title", text: mode.label }));
      items.forEach((item) => {
        if (item.kind === "section") {
          legendEl.appendChild(el("div", { class: "viz-legend-title", text: item.title, style: "margin-top:6px" }));
        } else if (item.kind === "swatch") {
          legendEl.appendChild(el("div", { class: "viz-legend-row" }, [
            el("span", { class: "viz-legend-swatch", style: "background:" + item.color }),
            document.createTextNode(item.label),
          ]));
        } else if (item.kind === "ramp") {
          const ramp = el("div", { class: "viz-legend-ramp" });
          item.steps.forEach((s) => ramp.appendChild(el("span", { style: "background:" + s.color })));
          legendEl.appendChild(ramp);
        } else if (item.kind === "text") {
          legendEl.appendChild(el("div", { class: "viz-legend-row", text: item.text }));
        }
      });
    }

    // -- detail panel ----------------------------------------------------------

    const panel = el("div", { class: "viz-panel" });

    function renderPanel() {
      const sel = state.get().selection;
      const mode = VizModes.getMode(state.get().mode);
      panel.innerHTML = "";
      const extras = mode.panelExtras(state.get(), payload);

      if (!sel && extras.length === 0) {
        panel.setAttribute("data-open", "false");
        return;
      }
      panel.setAttribute("data-open", "true");
      panel.appendChild(el("button", { class: "viz-panel-close", text: "✕", onClick: () => state.update({ selection: null }) }));

      if (sel) {
        const node = payload.nodes.find((n) => n.id === sel);
        if (node) {
          panel.appendChild(el("h2", { text: node.label }));
          const chips = el("div", { class: "viz-chips-row" });
          if (node.domain) chips.appendChild(el("span", { class: "viz-tag", text: node.domain }));
          if (node.type) chips.appendChild(el("span", { class: "viz-tag", text: node.type }));
          if (node.community_id != null) chips.appendChild(el("span", { class: "viz-tag", text: "community " + node.community_id }));
          panel.appendChild(chips);
          if (node.excerpt) {
            panel.appendChild(el("div", { class: "viz-section-title", text: "Excerpt" }));
            panel.appendChild(el("div", { class: "viz-excerpt", text: node.excerpt }));
          }
          const synapses = payload.edges
            .filter((e) => e.source === node.id || e.target === node.id)
            .sort((a, b) => b.weight - a.weight);
          if (synapses.length) {
            panel.appendChild(el("div", { class: "viz-section-title", text: "Synapses" }));
            const list = el("ul", { class: "viz-synapse-list" });
            synapses.forEach((e) => {
              const other = e.source === node.id ? e.target : e.source;
              const otherNode = payload.nodes.find((n) => n.id === other);
              const li = el("li", {
                class: "viz-synapse-item",
                text: (otherNode ? otherNode.label : other) + " — " + e.type + " (" + e.weight.toFixed(2) + ")",
                onClick: () => selectNode(other),
              });
              list.appendChild(li);
            });
            panel.appendChild(list);
          }
          panel.appendChild(el("button", {
            class: "viz-copy-id", text: "Copy ID",
            onClick: () => navigator.clipboard && navigator.clipboard.writeText(node.id),
          }));
        }
      }

      extras.forEach((section) => {
        panel.appendChild(el("div", { class: "viz-section-title", text: section.title }));
        const list = el("ul", { class: "viz-extras-list" });
        section.items.forEach((item) => {
          const li = el("li", {
            class: "viz-extras-item",
            text: item.label + (item.sublabel ? " (" + item.sublabel + ")" : ""),
            onClick: () => {
              if (item.payload && item.payload.source) {
                selectNode(item.payload.source);
              }
            },
          });
          list.appendChild(li);
        });
        panel.appendChild(list);
      });
    }

    // -- toolbar ---------------------------------------------------------------

    const toolbar = el("div", { class: "viz-toolbar" }, [
      el("button", { text: "Fit", onClick: () => render.fit() }),
      el("button", {
        text: "Re-layout",
        onClick: () => window.dispatchEvent(new CustomEvent("viz:relayout")),
      }),
    ]);

    // -- assembly ----------------------------------------------------------------

    root.appendChild(topbar);
    root.appendChild(legendEl);
    root.appendChild(panel);
    root.appendChild(toolbar);

    // -- selection / ego wiring --------------------------------------------------

    function selectNode(nodeId) {
      state.update({ selection: nodeId });
    }

    state.subscribe((s, prev) => {
      if (s.mode !== prev.mode) {
        render.repaint(s.mode);
        VizModes.MODES.forEach((mode, i) => {
          modeBar.children[i].setAttribute("aria-pressed", String(mode.id === s.mode));
        });
        renderLegend();
        renderPanel();
      }
      if (s.selection !== prev.selection) {
        render.setHighlight(s.selection);
        renderPanel();
      }
      if (s.ego !== prev.ego) {
        render.setEgo(s.ego ? s.ego.center : null, s.ego ? s.ego.depth : 0);
      }
    });

    renderLegend();
    renderPanel();

    // -- keyboard shortcuts --------------------------------------------------

    window.addEventListener("keydown", (ev) => {
      if (document.activeElement === searchInput) {
        if (ev.key === "Escape") { searchInput.blur(); searchResults.style.display = "none"; }
        return;
      }
      const mode = VizModes.MODES.find((m) => m.hotkey === ev.key);
      if (mode && !(mode.requires && mode.requires !== overlay)) {
        state.update({ mode: mode.id });
        return;
      }
      if (ev.key === "m") {
        const ids = VizModes.MODES.filter((m) => !(m.requires && m.requires !== overlay)).map((m) => m.id);
        const idx = ids.indexOf(state.get().mode);
        state.update({ mode: ids[(idx + 1) % ids.length] });
      } else if (ev.key === "/") {
        ev.preventDefault();
        searchInput.focus();
      } else if (ev.key === "f") {
        render.fit();
      } else if (ev.key === "d") {
        panel.setAttribute("data-open", panel.getAttribute("data-open") === "true" ? "false" : "true");
      } else if (ev.key === "Escape") {
        state.update({ selection: null, ego: null });
      }
    });

    return { selectNode };
  }

  window.VizUI = { mount };
})();
