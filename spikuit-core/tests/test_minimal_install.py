"""Verify the lightweight install boundary.

These tests ensure `spikuit_core` can be imported without pulling the
engine dependencies (networkx, aiosqlite, sqlite-vec, msgspec) into
`sys.modules`. They simulate a `pip install spikuit-core` (no extras)
by inspecting which modules get loaded.
"""

from __future__ import annotations

import importlib
import sys

import pytest


_ENGINE_DEPS = {"networkx", "aiosqlite", "sqlite_vec", "msgspec"}


def _fresh_import(modname: str):
    for k in list(sys.modules):
        if k == modname or k.startswith(modname + "."):
            del sys.modules[k]
    return importlib.import_module(modname)


def test_top_level_import_does_not_load_engine_deps():
    # Snapshot which engine deps are already loaded by other tests
    pre_loaded = {dep for dep in _ENGINE_DEPS if dep in sys.modules}

    # Re-import spikuit_core fresh
    _fresh_import("spikuit_core")

    # Engine deps that were NOT loaded before importing spikuit_core
    # should still not be loaded after the import.
    newly_loaded = {dep for dep in _ENGINE_DEPS if dep in sys.modules} - pre_loaded
    assert not newly_loaded, (
        f"Bare `import spikuit_core` pulled engine deps: {newly_loaded}"
    )


def test_qabot_importable_without_engine_modules():
    pre_loaded = {dep for dep in _ENGINE_DEPS if dep in sys.modules}

    for k in list(sys.modules):
        if k == "spikuit_core" or k.startswith("spikuit_core."):
            del sys.modules[k]

    importlib.import_module("spikuit_core.rag.qabot")

    newly_loaded = {dep for dep in _ENGINE_DEPS if dep in sys.modules} - pre_loaded
    assert not newly_loaded, (
        f"`import spikuit_core.rag.qabot` pulled engine deps: {newly_loaded}"
    )


def test_engine_symbol_lazy_load_succeeds_in_full_env():
    """In the dev env [engine] extras are installed, so lazy access works."""
    import spikuit_core

    # Use getattr to trigger __getattr__
    Circuit = spikuit_core.Circuit
    Neuron = spikuit_core.Neuron
    assert Circuit is not None
    assert Neuron is not None


def test_engine_symbol_friendly_error_when_dep_missing(monkeypatch):
    """If an engine dep is unavailable at import time, accessing an
    engine symbol must raise ImportError pointing to `[engine]` extras."""
    import spikuit_core

    # Drop cached lazy-loaded engine modules so __getattr__ re-imports
    for name in (
        "spikuit_core.circuit",
        "spikuit_core.models",
        "spikuit_core.db",
        "spikuit_core.propagation",
    ):
        sys.modules.pop(name, None)

    # Also drop any cached top-level engine symbols on the package
    for name in ("Circuit", "Neuron", "ReadOnlyError"):
        spikuit_core.__dict__.pop(name, None)

    # Force the next import of `networkx` to fail (Circuit imports networkx).
    real_import = importlib.import_module

    def fake_import(name, *args, **kwargs):
        if name == "networkx" or name.startswith("networkx."):
            raise ImportError("No module named 'networkx'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(importlib, "import_module", fake_import)
    sys.modules.pop("networkx", None)
    monkeypatch.setitem(
        sys.modules, "networkx", None  # type: ignore[arg-type]
    )

    with pytest.raises(ImportError, match=r"spikuit-core\[engine\]"):
        _ = spikuit_core.Circuit


def test_minimal_install_can_load_qabot_bundle(tmp_path):
    """Smoke test: the always-available surface is enough to construct a
    QABot from a bundle. We build the bundle using the engine (which IS
    installed in dev), then load it via the lightweight surface."""
    import asyncio

    from spikuit_core import Circuit, Neuron, QABot
    from spikuit_core.config import BrainConfig, EmbedderConfig
    from spikuit_core.export import export_qabot_bundle

    async def _build():
        c = Circuit(db_path=tmp_path / "b.db")
        await c.connect()
        try:
            await c.add_neuron(
                Neuron.create("---\ntype: concept\ndomain: math\n---\n# Monad\n\nbody")
            )
            cfg = BrainConfig(
                name="t",
                root=tmp_path,
                embedder=EmbedderConfig(provider="none"),
            )
            out = tmp_path / "bundle.db"
            await export_qabot_bundle(c, cfg, out)
            return out
        finally:
            await c.close()

    bundle = asyncio.run(_build())
    brain = QABot.load(bundle)
    assert brain.stats()["neurons"] == 1
