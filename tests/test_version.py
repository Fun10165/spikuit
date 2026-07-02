"""Smoke test for the spikuit meta-package's version.

Regression guard: __version__ used to be a literal in
src/spikuit/__init__.py, hand-edited and drifting from pyproject.toml's
declared version (it was stuck at 0.6.1 while the package shipped 0.9.0).
It's now resolved from installed package metadata.
"""

from __future__ import annotations

from importlib.metadata import version

import spikuit


def test_version_matches_installed_metadata():
    assert spikuit.__version__ == version("spikuit")
