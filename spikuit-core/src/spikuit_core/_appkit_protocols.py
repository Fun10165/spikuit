"""Structural Protocols behind the spikuit-core app contract.

Internal module. Application packages reach these names through
``spikuit_core.appkit`` — never import ``_appkit_protocols`` directly.

The Protocols capture exactly the substrate surface the tutor app (and
any other adapter) depends on, so the concrete ``Circuit`` / ``Neuron``
engine types can be refactored freely as long as they keep satisfying
these shapes. See ``docs/design/tutor-extraction-stage1.md`` §2.1–§2.2
and ``docs/design/tutor-extraction-stage2.md`` §4.6.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Protocol, runtime_checkable

if TYPE_CHECKING:
    from datetime import datetime

    from .models import Spike


@runtime_checkable
class NeuronView(Protocol):
    """Read-only view of a neuron — the fields app code reads off one.

    ``spikuit_core.Neuron`` satisfies this structurally. App code type-hints
    against ``NeuronView`` so the concrete struct can grow internal fields
    without widening the contract.
    """

    id: str
    content: str
    domain: str | None
    type: str
    created_at: datetime


@runtime_checkable
class SubstrateView(Protocol):
    """The subset of ``Circuit`` an app (the tutor, an agent) calls.

    ``spikuit_core.Circuit`` satisfies this structurally. App code receives
    a ``SubstrateView`` by dependency injection and never constructs one.

    As of Stage 2 (§4.6) the substrate owns no learner model: the FSRS
    ``due_neurons`` / ``near_due_neurons`` queries are gone, and ``fire``
    only applies grade-driven plasticity (it returns nothing). The view
    instead exposes the graph topology and spike history the tutor needs
    to run scheduling and scaffolding itself.
    """

    async def fire(self, spike: Spike) -> None: ...

    async def get_neuron(self, neuron_id: str) -> NeuronView | None: ...

    async def list_neurons(self, *, limit: int = ...) -> list[NeuronView]: ...

    async def get_spikes_for(
        self, neuron_id: str, *, limit: int = ...
    ) -> list[Spike]: ...

    def neighbors(self, neuron_id: str) -> list[str]: ...

    def predecessors(self, neuron_id: str) -> list[str]: ...

    def edge_type(self, pre: str, post: str) -> str | None: ...
