"""Stable app-facing surface of spikuit-core.

Application packages (``spikuit-tutor``, ``spikuit-agent-rag``) import ONLY
from ``spikuit_core.appkit`` — never from spikuit_core internals. This
module is the versioned, semver-stable contract: substrate internals
(``circuit``, ``propagation``, ``community``, ``spectral``, ``db``) may
churn freely behind it. The boundary is enforced in CI by
``tools/check_app_imports.py``.

See ``docs/design/tutor-extraction-stage1.md`` §4.1.
"""

from __future__ import annotations

from ._appkit_protocols import NeuronView, SchedulerCircuit
from .models import Grade, Scaffold, ScaffoldLevel, Spike
from .scaffold import compute_scaffold

__all__ = [
    "Grade",
    "NeuronView",
    "Scaffold",
    "ScaffoldLevel",
    "SchedulerCircuit",
    "Spike",
    "compute_scaffold",
]
