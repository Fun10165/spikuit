"""Inline the viz app + vendored libraries + payload into one self-contained
HTML file. docs/design/graph-viz.md §2, §9.

No bundler. ``index.html``'s placeholders get replaced with the literal file
contents in dependency order — the shipped artifact opens from ``file://``
with zero network access.
"""

from __future__ import annotations

import json
from importlib import resources
from typing import Any

_VENDOR_ORDER = [
    "graphology.umd.min.js",
    "sigma.min.js",
    "graphology-layout-forceatlas2.bundle.js",
]

# Dependency order matters: state/modes have no app deps; physics only needs
# the vendored FA2Layout global; render needs modes + the vendored graph libs;
# ui needs modes + state; main needs everything and must load last.
_APP_SCRIPT_ORDER = [
    "state.js",
    "modes.js",
    "physics.js",
    "render.js",
    "ui.js",
    "main.js",
]


def _read(package: str, filename: str) -> str:
    return resources.files(package).joinpath(filename).read_text(encoding="utf-8")


def _script_tag(js: str) -> str:
    # Guard against a literal "</script>" inside vendored/app source closing
    # the tag early — none of our sources contain it today, but a vendor
    # update could introduce one silently.
    return "<script>\n" + js.replace("</script>", "<\\/script>") + "\n</script>"


def build_html(payload: dict[str, Any]) -> str:
    """Render the graph-viz app for ``payload`` as one self-contained HTML
    document. Pure string transformation — no file I/O beyond reading the
    package's own bundled template/vendor/app sources.
    """
    template = _read("spikuit_cli.viz.app", "index.html")
    theme_css = _read("spikuit_cli.viz.app", "theme.css")

    vendor_scripts = "\n".join(
        _script_tag(_read("spikuit_cli.viz.vendor", name)) for name in _VENDOR_ORDER
    )
    app_scripts = "\n".join(
        _script_tag(_read("spikuit_cli.viz.app", name)) for name in _APP_SCRIPT_ORDER
    )

    # </script> escaped the same way as vendored/app sources, for the same
    # reason: a neuron title or excerpt containing that literal substring
    # must not be able to close the data island early.
    data_json = json.dumps(payload, ensure_ascii=False).replace("</script>", "<\\/script>")

    html = template
    html = html.replace("<!-- APP_STYLES -->", theme_css)
    html = html.replace("<!-- GRAPH_DATA -->", data_json)
    html = html.replace("<!-- VENDOR_SCRIPTS -->", vendor_scripts)
    html = html.replace("<!-- APP_SCRIPTS -->", app_scripts)
    return html
