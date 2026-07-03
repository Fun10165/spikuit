"""Unit tests for spikuit_cli.viz.build.build_html.

See docs/design/graph-viz.md §9: data island extract -> json.loads OK;
</script> escaping; all vendor bundles + modules present exactly once;
both theme token sets.
"""

from __future__ import annotations

import json
import re

from spikuit_cli.viz.build import build_html


def _payload(**overrides):
    base = {
        "meta": {
            "generated_at": "2026-07-02T00:00:00+00:00",
            "neuron_count": 1,
            "synapse_count": 0,
            "size_by": "centrality",
            "coloring": "domain",
            "overlay": None,
            "component_count": 1,
            "weight_domain": [0.0, 1.0],
        },
        "groups": [{"key": "math", "kind": "domain", "label": "math", "count": 1, "slot": 1}],
        "nodes": [{
            "id": "n1", "label": "Functor", "group": 1, "size_raw": 0.5,
            "domain": "math", "type": "concept", "pressure": 0.0, "community_id": None,
            "component_id": 0, "excerpt": "A map between categories.",
            "spike_recency": None, "tutor": None,
        }],
        "edges": [],
    }
    base.update(overrides)
    return base


def _extract_data_island(html: str) -> str:
    m = re.search(
        r'<script type="application/json" id="graph-data">\s*(.*?)\s*</script>',
        html, re.S,
    )
    assert m is not None, "graph-data script tag not found"
    return m.group(1)


def test_data_island_round_trips_through_json():
    html = build_html(_payload())
    data = json.loads(_extract_data_island(html))
    assert data["nodes"][0]["label"] == "Functor"
    assert data["meta"]["neuron_count"] == 1


def test_script_tag_escaping_prevents_early_close():
    evil = _payload()
    evil["nodes"][0]["label"] = 'Evil</script><script>alert(1)</script>'
    html = build_html(evil)
    # The literal "</script>" must not appear unescaped inside the data
    # island's payload content -- only as an actual tag boundary.
    island_raw = _extract_data_island(html)
    assert "</script>" not in island_raw
    # And the round-trip still recovers the exact original string as data.
    data = json.loads(island_raw.replace("<\\/script>", "</script>"))
    assert data["nodes"][0]["label"] == 'Evil</script><script>alert(1)</script>'


def test_vendor_and_app_scripts_present_exactly_once():
    html = build_html(_payload())
    # 3 vendor bundles + 6 app modules + 1 JSON data island = 10 <script> tags.
    assert html.count("<script") == 10
    # Each module's own distinguishing top-of-file comment appears exactly
    # once — would fail if a placeholder got substituted twice.
    markers = [
        "Single state store",  # state.js
        "ViewSpec registry",  # modes.js
        "ForceAtlas2 lifecycle",  # physics.js
        "only module that touches sigma/graphology",  # render.js
        "Mode bar, filter row, detail panel",  # ui.js
        "// Bootstrap.",  # main.js
        "window.FA2Layout",  # vendored bundle's own global assignment
    ]
    for marker in markers:
        assert html.count(marker) == 1, marker


def test_app_modules_present_in_dependency_order():
    html = build_html(_payload())
    order = ["VizState", "VizModes", "VizPhysics", "VizRender", "VizUI", "function main"]
    positions = [html.index(marker) for marker in order]
    assert positions == sorted(positions), "app modules must be inlined in dependency order"


def test_both_theme_token_sets_present():
    html = build_html(_payload())
    assert "--surface: #1a1a19" in html  # dark (default)
    assert "prefers-color-scheme: light" in html
    assert "--surface: #fcfcfb" in html  # light override


def test_no_adversarial_content_leaks_outside_the_data_island():
    evil = _payload()
    evil["nodes"][0]["excerpt"] = '<img src=x onerror="alert(1)">'
    html = build_html(evil)
    before_island = html.split('<script type="application/json" id="graph-data">')[0]
    assert "onerror" not in before_island


def test_node_labels_use_the_theme_ink_token_not_sigmas_black_default():
    # Regression: sigma's node-label canvas layer is separate from the
    # CSS-themed chrome and defaults to black text, which is invisible
    # against the dark surface. render.js must pass an explicit
    # labelColor sourced from the --text-1 token (white in dark mode)
    # rather than relying on sigma's own default.
    html = build_html(_payload())
    assert "labelColor" in html
    assert "ctx.tokens.text1" in html


def test_label_density_is_tuned_down_from_sigma_defaults():
    # Regression: a real ~230-node brain rendered with every node's label
    # always on (labelRenderedSizeThreshold: 0) produced illegible text
    # soup — sigma's default occlusion grid is keyed on node position, not
    # label text width, so long bilingual labels overlapped even when
    # nodes themselves weren't crowded. Labels are still reachable via
    # hover/selection (forceLabel in the node reducer); this only trims
    # the always-on set.
    html = build_html(_payload())
    assert "labelRenderedSizeThreshold: 0" not in html
    assert "labelGridCellSize" in html
    assert "labelDensity" in html


def test_weight_slider_resets_native_appearance():
    # Regression: a real browser (reported directly by the user) rendered
    # the weight-threshold range input at ~8-10x its intended size — a
    # plain `width: 90px` doesn't reliably override a native range input's
    # own chrome in every browser/OS combination (observed correct in this
    # project's own headless Chromium and WebKit test runs, but not in the
    # user's actual browser, most likely due to OS-level control scaling).
    # `appearance: none` + custom thumb/track pseudo-elements is the
    # standard, fully robust fix — it removes native chrome entirely
    # rather than trying to override it.
    html = build_html(_payload())
    assert "appearance: none" in html
    assert "::-webkit-slider-thumb" in html
    assert "::-moz-range-thumb" in html
