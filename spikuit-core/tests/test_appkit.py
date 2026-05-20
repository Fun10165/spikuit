"""Tests for the ``spikuit_core.appkit`` contract surface.

``appkit`` is the curated, semver-stable module application packages
(``spikuit-tutor``, ``spikuit-agent-rag``) import from. These tests pin
its exported surface and verify the concrete engine types still satisfy
the structural Protocols the contract promises — so substrate
refactors that quietly break the app boundary fail here.
"""

from __future__ import annotations

from spikuit_core import appkit
from spikuit_core.appkit import NeuronView, SubstrateView
from spikuit_core.circuit import Circuit
from spikuit_core.models import Neuron


def test_appkit_exports_exactly_the_documented_surface():
    assert sorted(appkit.__all__) == [
        "Grade",
        "NeuronView",
        "Spike",
        "SubstrateView",
    ]
    for name in appkit.__all__:
        assert hasattr(appkit, name), f"appkit.__all__ names {name} but it is missing"


def test_circuit_satisfies_substrate_view():
    # SubstrateView is a method-only Protocol — issubclass is valid.
    assert issubclass(Circuit, SubstrateView)


def test_neuron_satisfies_neuron_view():
    # NeuronView has data members — runtime_checkable supports isinstance
    # on an instance, not issubclass on the class.
    neuron = Neuron.create("# Functor\n\nA structure-preserving map between categories.")
    assert isinstance(neuron, NeuronView)
