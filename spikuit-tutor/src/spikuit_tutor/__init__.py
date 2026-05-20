"""Spikuit tutor application.

Extracted from ``spikuit-cli`` in v0.7.x as part of the substrate/app
split (see ``docs/design/roadmap.md`` §6). Holds the tutor engine
(``spikuit_tutor.tutor``) and quiz rendering (``spikuit_tutor.quiz``).

Stage 0 of the extraction is a package-boundary move only: this package
still depends on ``spikuit-core`` for shared domain types. The
``from spikuit_core`` imports are replaced in Stage 1.
"""
