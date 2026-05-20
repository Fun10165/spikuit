"""Spikuit tutor application.

Extracted from ``spikuit-cli`` in v0.7.x as part of the substrate/app
split (see ``docs/design/roadmap.md`` §6). Holds the tutor engine
(``spikuit_tutor.tutor``) and quiz rendering (``spikuit_tutor.quiz``).

Stage 1 of the extraction (v0.8.x) replaced the raw ``spikuit-core``
coupling with a controlled contract: this package imports ``spikuit-core``
only through ``spikuit_core.appkit`` — its curated, semver-stable surface.
Substrate internals are off-limits, and the boundary is enforced in CI by
``tools/check_app_imports.py``.

Stage 2 (v0.9.0, ``docs/design/tutor-extraction-stage2.md``) finishes
the extraction: FSRS scheduling state leaves ``spikuit-core`` entirely
and is re-homed here. :class:`TutorStore` is the overlay database,
:class:`TutorScheduler` owns the review loop, and ``compute_scaffold``
/ ``compute_progress`` are the learner-model computations that used to
live in the substrate.
"""

from __future__ import annotations

from .progress import compute_progress
from .scaffold import Scaffold, ScaffoldLevel, compute_scaffold
from .scheduler import TutorScheduler
from .store import TutorStore, default_overlay_path

__all__ = [
    "Scaffold",
    "ScaffoldLevel",
    "TutorScheduler",
    "TutorStore",
    "compute_progress",
    "compute_scaffold",
    "default_overlay_path",
]
