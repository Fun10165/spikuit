"""Structural Protocols behind the spikuit-core app contract.

Internal module. Application packages reach these names through
``spikuit_core.appkit`` — never import ``_appkit_protocols`` directly.

The Protocols capture exactly the substrate surface the tutor app (and
any other adapter) depends on, so the concrete ``Circuit`` / ``Neuron``
engine types can be refactored freely as long as they keep satisfying
these shapes. See ``docs/design/tutor-extraction-stage1.md`` §2.1–§2.2.
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


@runtime_checkable
class SchedulerCircuit(Protocol):
    """The subset of ``Circuit`` the tutor app calls.

    ``spikuit_core.Circuit`` satisfies this structurally. App code receives
    a ``SchedulerCircuit`` by dependency injection and never constructs one.
    """

    async def fire(self, spike: Spike) -> object: ...

    async def get_neuron(self, neuron_id: str) -> NeuronView | None: ...

    async def due_neurons(
        self, *, now: datetime | None = ..., limit: int = ...
    ) -> list[str]: ...

    async def near_due_neurons(
        self,
        *,
        days_ahead: int = ...,
        limit: int = ...,
        exclude_ids: set[str] | None = ...,
        now: datetime | None = ...,
    ) -> list[str]: ...
