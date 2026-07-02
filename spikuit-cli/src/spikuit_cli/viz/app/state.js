// Single state store + pub/sub. No framework, no external state lib.
// docs/design/graph-viz.md §8.

(function () {
  "use strict";

  function createState(initial) {
    const state = Object.assign(
      {
        mode: "links",
        selection: null,
        ego: null, // { center, depth }
        filters: { groups: null, edgeTypes: null, nodeTypes: null, weightMin: 0 },
        theme: matchMedia("(prefers-color-scheme: light)").matches ? "light" : "dark",
      },
      initial || {}
    );

    const subscribers = [];

    function subscribe(fn) {
      subscribers.push(fn);
      return function unsubscribe() {
        const i = subscribers.indexOf(fn);
        if (i !== -1) subscribers.splice(i, 1);
      };
    }

    function update(patch) {
      const prev = Object.assign({}, state);
      Object.assign(state, typeof patch === "function" ? patch(state) : patch);
      subscribers.forEach((fn) => fn(state, prev));
    }

    function get() {
      return state;
    }

    return { get, update, subscribe };
  }

  window.VizState = { createState };
})();
