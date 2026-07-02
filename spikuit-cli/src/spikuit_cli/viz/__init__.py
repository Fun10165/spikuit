"""Graph visualization: data contract + (later) app build.

See docs/design/graph-viz.md for the full spec. ``payload`` is the only
module implemented so far (Phase E0).
"""

from __future__ import annotations

from .payload import build_viz_payload

__all__ = ["build_viz_payload"]
