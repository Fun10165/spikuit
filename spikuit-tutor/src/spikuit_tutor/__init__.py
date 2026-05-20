"""Spikuit tutor application.

Extracted from ``spikuit-cli`` in v0.7.x as part of the substrate/app
split (see ``docs/design/roadmap.md`` §6). Holds the tutor engine
(``spikuit_tutor.tutor``) and quiz rendering (``spikuit_tutor.quiz``).

Stage 1 of the extraction (v0.8.x) replaced the raw ``spikuit-core``
coupling with a controlled contract: this package imports ``spikuit-core``
only through ``spikuit_core.appkit`` — its curated, semver-stable surface.
Substrate internals are off-limits, and the boundary is enforced in CI by
``tools/check_app_imports.py``. The database is untouched until Stage 2.
"""
