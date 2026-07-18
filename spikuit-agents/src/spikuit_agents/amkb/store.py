"""SpikuitStore — sync amkb.Store backed by an async spikuit_core.Circuit.

All operations route through a single persistent background event loop
so the underlying `aiosqlite` connection stays bound to one thread for
the lifetime of the store.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Iterator, Literal

from amkb.errors import (
    EChangesetNotFound,
    EEdgeNotFound,
    EInvalid,
    ENodeNotFound,
)
from amkb.filters import And, Eq, In, Not, Or, Range
from amkb.refs import (
    ActorId,
    ChangeSetRef,
    EdgeRef,
    NodeRef,
    Timestamp,
    TransactionRef,
)
from amkb.store import RetrievalHit
from amkb.types import Actor, ChangeSet, Edge, Event, Node
from spikuit_core import Circuit
from spikuit_core.models import SynapseType

from spikuit_agents.amkb._ids import decode_edge_ref
from spikuit_agents.amkb._loop import BackgroundLoop
from spikuit_agents.amkb.mapping import (
    dt_to_ts,
    neuron_to_node,
    rel_to_synapse_type,
    synapse_to_edge,
)
from spikuit_agents.amkb.transaction import (
    SpikuitStoreTransaction,
    make_event,
)


def _iso_to_ts(iso: str | None) -> Timestamp:
    if iso is None:
        return Timestamp(0)
    dt = datetime.fromisoformat(iso)
    return dt_to_ts(dt)


class SpikuitStore:
    """An amkb.Store backed by a `spikuit_core.Circuit` instance."""

    def __init__(self, circuit: Circuit, *, loop: BackgroundLoop | None = None) -> None:
        self._circuit = circuit
        self._loop = loop or BackgroundLoop()
        self._owns_loop = loop is None

    @classmethod
    def open(cls, db_path: str, **circuit_kwargs: Any) -> "SpikuitStore":
        """Convenience: build a Circuit, connect it on the bg loop, return store."""
        loop = BackgroundLoop()
        circuit = Circuit(db_path=db_path, **circuit_kwargs)
        loop.run(circuit.connect())
        store = cls(circuit, loop=loop)
        store._owns_loop = True
        return store

    def close(self) -> None:
        try:
            self._loop.run(self._circuit.close())
        finally:
            if self._owns_loop:
                self._loop.close()

    # -- session -----------------------------------------------------------

    def begin(self, *, tag: str, actor: Actor) -> SpikuitStoreTransaction:
        actor_kind: Literal["human", "agent", "system"]
        if actor.kind == "human":
            actor_kind = "human"
        elif actor.kind in ("automation", "composite"):
            actor_kind = "system"
        else:
            actor_kind = "agent"
        return SpikuitStoreTransaction(
            circuit=self._circuit,
            loop=self._loop,
            tag=tag,
            actor_id=str(actor.id),
            actor_kind=actor_kind,
        )

    # -- read queries ------------------------------------------------------

    def get_node(self, ref: NodeRef) -> Node:
        async def _do() -> Node:
            db = self._circuit._db  # noqa: SLF001
            live = await db.get_neuron(str(ref))
            if live is not None:
                return neuron_to_node(live)
            any_neuron = await db.get_neuron(str(ref), include_retired=True)
            if any_neuron is None:
                raise ENodeNotFound(f"node not found: {ref}", ref=str(ref))
            retired_at = await db.get_neuron_retired_at(str(ref))
            return neuron_to_node(any_neuron, retired_at=retired_at)

        return self._loop.run(_do())

    def get_edge(self, ref: EdgeRef) -> Edge:
        pre, post, rel = decode_edge_ref(ref)
        try:
            stype = rel_to_synapse_type(rel)
        except ValueError as exc:
            raise EEdgeNotFound(f"edge not found: {ref}", ref=str(ref)) from exc

        async def _do() -> Edge:
            syn = await self._circuit.get_synapse(pre, post, stype)
            if syn is None:
                raise EEdgeNotFound(f"edge not found: {ref}", ref=str(ref))
            return synapse_to_edge(syn)

        return self._loop.run(_do())

    def find_by_attr(
        self,
        attributes: dict[str, Any],
        *,
        kind: str | None = None,
        layer: str | None = None,
        include_retired: bool = False,
        limit: int = 100,
    ) -> list[NodeRef]:
        async def _do() -> list[NodeRef]:
            neurons = await self._circuit._db.list_neurons(  # noqa: SLF001
                limit=limit, include_retired=include_retired,
            )
            results: list[NodeRef] = []
            for n in neurons:
                attrs = {
                    "type": n.type,
                    "domain": n.domain,
                    "source": n.source,
                }
                if all(attrs.get(k) == v for k, v in attributes.items()):
                    results.append(NodeRef(n.id))
            return results

        return self._loop.run(_do())

    def neighbors(
        self,
        ref: NodeRef,
        *,
        rel: str | list[str] | None = None,
        direction: str = "out",
        depth: int = 1,
        include_retired: bool = False,
        limit: int = 100,
    ) -> list[NodeRef]:
        if depth < 1:
            raise EInvalid(
                f"neighbors depth must be >= 1, got {depth}", depth=depth,
            )

        async def _do() -> list[NodeRef]:
            db = self._circuit._db  # noqa: SLF001
            visited: set[str] = {str(ref)}
            frontier: list[str] = [str(ref)]
            ordered: list[str] = []
            for _ in range(depth):
                next_frontier: list[str] = []
                for node_id in frontier:
                    if direction == "out":
                        out_ids = self._circuit.neighbors(node_id)
                    elif direction == "in":
                        out_ids = self._circuit.predecessors(node_id)
                    else:
                        out_ids = list(
                            set(self._circuit.neighbors(node_id))
                            | set(self._circuit.predecessors(node_id))
                        )
                    for nid in out_ids:
                        if nid in visited:
                            continue
                        neuron = await db.get_neuron(nid)
                        if neuron is None:
                            continue
                        # AMKB invariant: kind=source MUST NOT appear in walks.
                        if neuron.type == "source":
                            visited.add(nid)
                            continue
                        visited.add(nid)
                        ordered.append(nid)
                        next_frontier.append(nid)
                frontier = next_frontier
                if not frontier:
                    break
            return [NodeRef(i) for i in ordered[:limit]]

        return self._loop.run(_do())

    def retrieve(
        self,
        intent: str,
        *,
        k: int = 10,
        layer: str | list[str] | None = None,
        filters: Any = None,
    ) -> list[RetrievalHit]:
        if k < 1:
            raise EInvalid(f"retrieve k must be >= 1, got {k}", k=k)
        if filters is not None and not isinstance(
            filters, (Eq, In, Range, And, Or, Not),
        ):
            raise EInvalid(
                f"unsupported filter operator: {type(filters).__name__}",
            )

        async def _do() -> list[RetrievalHit]:
            scored = await self._circuit.retrieve_scored(intent, limit=k * 2)
            hits: list[RetrievalHit] = []
            for neuron, score in scored:
                if neuron.type == "source":
                    continue  # AMKB invariant: source kind excluded
                hits.append(RetrievalHit(ref=NodeRef(neuron.id), score=score))
                if len(hits) >= k:
                    break
            return hits

        return self._loop.run(_do())

    # -- history -----------------------------------------------------------

    def history(
        self,
        *,
        since: Timestamp | None = None,
        until: Timestamp | None = None,
        actor: ActorId | None = None,
        tag: str | None = None,
        limit: int = 100,
    ) -> list[ChangeSetRef]:
        async def _do() -> list[ChangeSetRef]:
            sql = (
                "SELECT id FROM changeset WHERE status='committed'"
            )
            params: list[object] = []
            if tag is not None:
                sql += " AND tag = ?"
                params.append(tag)
            if actor is not None:
                sql += " AND actor_id = ?"
                params.append(str(actor))
            sql += " ORDER BY committed_at, id LIMIT ?"
            params.append(limit)
            cur = await self._circuit._db.conn.execute(sql, tuple(params))  # noqa: SLF001
            rows = await cur.fetchall()
            return [ChangeSetRef(row["id"]) for row in rows]

        return self._loop.run(_do())

    def get_changeset(self, ref: ChangeSetRef) -> ChangeSet:
        async def _do() -> ChangeSet:
            row = await self._circuit._db.get_changeset(str(ref))  # noqa: SLF001
            if row is None or row.get("status") != "committed":
                raise EChangesetNotFound(
                    f"changeset not found: {ref}", ref=str(ref),
                )
            event_dicts = await self._circuit._db.list_events(  # noqa: SLF001
                changeset_id=str(ref),
            )
            events: list[Event] = []
            for ed in event_dicts:
                ev = make_event(
                    op=ed["op"],
                    target_kind=ed["target_kind"],
                    target_id=ed["target_id"],
                    before_json=ed["before_json"],
                    after_json=ed["after_json"],
                )
                if ev is not None:
                    events.append(ev)
            return ChangeSet(
                ref=ChangeSetRef(row["id"]),
                tx_ref=TransactionRef(row["id"]),
                tag=row.get("tag") or "",
                actor=ActorId(row["actor_id"]),
                committed_at=_iso_to_ts(row.get("committed_at")),
                events=tuple(events),
            )

        return self._loop.run(_do())

    def diff(self, from_ts: Timestamp, to_ts: Timestamp) -> list[Event]:
        # L1 doesn't exercise diff. Stub for protocol completeness.
        all_events = list(self.events())
        return [
            e for e in all_events
            # No timestamp on Event; placeholder until events expose `at`
        ]

    def revert(
        self,
        target: ChangeSetRef | str,
        *,
        reason: str,
        actor: Actor,
    ) -> ChangeSet:
        raise NotImplementedError("revert is not supported in v0.7.1 adapter")

    # -- events ------------------------------------------------------------

    def events(
        self,
        *,
        since: Timestamp | None = None,
        follow: bool = False,
    ) -> Iterator[Event]:
        async def _do() -> list[Event]:
            event_dicts = await self._circuit._db.list_events(limit=10_000)  # noqa: SLF001
            results: list[Event] = []
            for ed in event_dicts:
                ev = make_event(
                    op=ed["op"],
                    target_kind=ed["target_kind"],
                    target_id=ed["target_id"],
                    before_json=ed["before_json"],
                    after_json=ed["after_json"],
                )
                if ev is not None:
                    results.append(ev)
            return results

        return iter(self._loop.run(_do()))
