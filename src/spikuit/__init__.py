"""Spikuit — meta-distribution.

Installing `spikuit` pulls in `spikuit-cli` (the `spkt` command) and
`spikuit-core[engine]` (the full Brain engine). Import from
`spikuit_core` and `spikuit_cli` directly; this package is intentionally
empty and exists only to provide a single install target.
"""

from importlib.metadata import PackageNotFoundError, version

try:
    __version__ = version("spikuit")
except PackageNotFoundError:  # running from a source tree without install
    __version__ = "0.0.0+unknown"
